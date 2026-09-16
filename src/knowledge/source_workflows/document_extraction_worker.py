"""Execute queued document extraction without holding knowledge transactions.

The worker pins source PDFs, combines Docling and selected Marker pages, validates
coverage, and persists one immutable snapshot.
"""

import fcntl
import hashlib
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from types import FrameType
from typing import NoReturn
from urllib.error import URLError

from knowledge.document_processing import (
    docling_parser,
    document_models,
    extraction_quality,
    extraction_store,
    extraction_tool_runner,
    marker_parser,
)
from knowledge.knowledge_base import source_records as sources
from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.literature import zotero_client as zotero
from knowledge.revision_store import postgresql_revision_store
from knowledge.runtime_support import environment_settings, workflow_event_log


def run_pending(settings: environment_settings.Settings) -> None:
    """Drain queued jobs under one server-local worker lock and recover interruptions."""
    root = settings.archive_root.parent
    database = postgresql_revision_store.Database(settings.database_url)
    signal.signal(signal.SIGTERM, stop_worker)
    with (root / "extraction-worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with database.transaction() as ledger:
            extraction_store.recover_jobs(ledger)
        drain_queue(database, root)


def stop_worker(signum: int, frame: FrameType | None) -> NoReturn:
    """Unwind temporary-file and child-unit cleanup when systemd stops the worker."""
    raise SystemExit(128 + signum)


def drain_queue(database: postgresql_revision_store.Database, root: Path) -> None:
    """Process one expensive job at a time while keeping failures inspectable."""
    while True:
        with database.transaction() as ledger:
            job = extraction_store.claim_job(ledger)
        if job is None:
            return
        execute_job(database, job, root)


def execute_job(database: postgresql_revision_store.Database, job: dict, root: Path) -> None:
    """Commit a completed snapshot or retain a bounded, classified failure."""
    audit = root / "runs" / "extraction" / job["request_hash"]
    workflow_event_log.record_event(audit, "extraction_started", source=str(job["source_id"]))
    try:
        snapshot = process_source(database, job, root, audit)
        with database.transaction() as ledger:
            extraction_store.save_snapshot(ledger, job["request_hash"], snapshot)
        workflow_event_log.record_event(audit, "extraction_succeeded", blocks=len(snapshot.blocks))
    except Exception as error:
        transient = isinstance(error, (URLError, TimeoutError, subprocess.TimeoutExpired))
        with database.transaction() as ledger:
            extraction_store.fail_job(ledger, job["request_hash"], str(error), transient)
        workflow_event_log.record_event(
            audit, "extraction_failed", error=str(error), transient=transient
        )


def process_source(
    database: postgresql_revision_store.Database, job: dict, root: Path, audit: Path
) -> document_models.DocumentSnapshot:
    """Resolve pinned Zotero bytes before extracting outside the transaction."""
    reference = models.Reference(entity_id=job["source_id"], revision=job["source_revision"])
    with database.transaction() as ledger:
        record = ledger.get(reference.entity_id, reference.revision)
        attachment = sources.zotero_reference(ledger, record)
    if not isinstance(record.payload, models.Source):
        raise ValueError("Extraction requires a source")
    pdf = zotero.verified_pdf(attachment, "original")
    clean_pdf = zotero.verified_pdf(attachment, "clean")
    with tempfile.TemporaryDirectory(prefix="knowledge-extraction-") as temporary:
        staging = Path(temporary)
        try:
            original = copy_pinned_pdf(pdf, staging / "original.pdf", attachment.original_sha256)
            cleaned = copy_pinned_pdf(clean_pdf, staging / "clean.pdf", attachment.clean_sha256)
            clean_pages = verified_page_map(original, cleaned)
            return extract_snapshot(original, reference, record.payload, clean_pages, staging, root)
        finally:
            preserve_logs(staging, audit)


def copy_pinned_pdf(source: Path, destination: Path, expected_hash: str) -> Path:
    """Freeze job input bytes and reject a Zotero file replaced during copying."""
    shutil.copyfile(source, destination)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("PDF changed while preparing extraction")
    destination.chmod(0o400)
    return destination


def extract_snapshot(
    pdf: Path,
    reference: models.Reference,
    source: models.Source,
    clean_pages: dict[int, int],
    staging: Path,
    root: Path,
) -> document_models.DocumentSnapshot:
    """Combine full-document structure with explicit visual second readings."""
    document = extraction_tool_runner.docling_document(pdf, staging / "docling", root)
    primary = [
        block
        for block in docling_parser.parse_document(document)
        if block.page is None or block.page in clean_pages
    ]
    sizes = docling_parser.page_sizes(document)
    scan_pages = pages_without_text(pdf) & clean_pages.keys()
    selected = scan_pages | {
        block.page
        for block in primary
        if block.page is not None and (block.kind == "table" or block.issues)
    }
    candidates = read_selected_pages(pdf, selected, sizes, staging, root)
    blocks = extraction_quality.reconcile_blocks(primary, candidates, scan_pages)
    issues = coverage_issues(blocks, clean_pages)
    return document_models.DocumentSnapshot(
        source=reference,
        zotero=source.zotero,
        pdf_sha256=source.sha256,
        blocks=blocks,
        page_sizes=sizes,
        clean_pages=clean_pages,
        method=extraction_store.CONFIGURATION,
        candidates=[block for block in primary if block.page in selected] + candidates,
        issues=[
            *issues,
            "Author-affiliation and citation-marker relationships require source review",
        ],
    )


def read_selected_pages(
    pdf: Path,
    pages: set[int],
    sizes: dict[int, tuple[float, float]],
    staging: Path,
    root: Path,
) -> list[document_models.DocumentBlock]:
    """Run each selected page through the same visual reading and location conversion."""
    candidates = []
    for page in sorted(pages):
        output = extraction_tool_runner.marker_document(pdf, page, staging / f"marker-{page}", root)
        candidates.extend(marker_parser.marker_blocks(output, page, sizes[page]))
    return candidates


def coverage_issues(
    blocks: list[document_models.DocumentBlock], clean_pages: dict[int, int]
) -> list[str]:
    """Reject empty output and make missing body-page coverage visible."""
    if not blocks:
        raise ValueError("Extraction produced no document content")
    covered = {block.page for block in blocks if block.text.strip() or block.cells or block.region}
    missing = sorted(clean_pages.keys() - covered)
    return [f"Document content missing on original pages: {missing}"] if missing else []


def pages_without_text(pdf: Path) -> set[int]:
    """Flag pages with fewer than forty text-layer characters for visual reading."""
    result = subprocess.run(["pdftotext", str(pdf), "-"], check=True, capture_output=True)
    pages = result.stdout.decode().split("\f")
    return {number for number, text in enumerate(pages[:-1], 1) if len(text.strip()) < 40}


def verified_page_map(original: Path, clean: Path) -> dict[int, int]:
    """Verify identity or cover removal against rasterized original and clean pages."""
    from pypdf import PdfReader

    original_pages, clean_pages = PdfReader(original).pages, PdfReader(clean).pages
    offset = len(original_pages) - len(clean_pages)
    if offset not in {0, 1}:
        raise ValueError("Cleaned PDF requires an explicit verified page map")
    if original == clean:
        return {index + 1: index + 1 for index in range(len(original_pages))}
    with tempfile.TemporaryDirectory(prefix="knowledge-page-map-") as temporary:
        original_hashes = rendered_page_hashes(original, Path(temporary) / "original")
        clean_hashes = rendered_page_hashes(clean, Path(temporary) / "clean")
    if original_hashes[offset:] != clean_hashes:
        raise ValueError("Cleaned PDF rendered pages differ; cannot infer navigation map")
    return {index + offset + 1: index + 1 for index in range(len(clean_pages))}


def rendered_page_hashes(pdf: Path, destination: Path) -> list[str]:
    """Hash ordered low-resolution page renders without retaining preview files."""
    destination.mkdir()
    subprocess.run(
        [
            "pdftoppm",
            "-r",
            "72",
            "-png",
            str(pdf),
            str(destination / "page"),
        ],
        capture_output=True,
        check=True,
        timeout=600,
    )
    pages = sorted(
        destination.glob("page-*.png"), key=lambda page: int(page.stem.rsplit("-", 1)[1])
    )
    return [hashlib.sha256(page.read_bytes()).hexdigest() for page in pages]


def preserve_logs(staging: Path, audit: Path) -> None:
    """Retain only tool diagnostics while disposable PDFs and images are removed."""
    for log in staging.rglob("*.log"):
        destination = audit / log.relative_to(staging)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(log, destination)
    for log in staging.rglob("events.jsonl"):
        destination = audit / log.relative_to(staging)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(log, destination)
