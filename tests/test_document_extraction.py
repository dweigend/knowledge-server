from pathlib import Path
from typing import LiteralString

import psycopg
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
from support import SeedArticle

import knowledge.document_processing.extraction_store as extraction
from knowledge.document_processing.document_models import DocumentBlock, DocumentSnapshot
from knowledge.knowledge_base.knowledge_service import Knowledge
from knowledge.knowledge_domain.knowledge_record_models import Reference, Source, ZoteroReference
from knowledge.revision_store.postgresql_revision_store import Ledger
from knowledge.source_workflows.document_extraction_worker import verified_page_map


@pytest.fixture
def source(application: Knowledge, article: SeedArticle) -> tuple[Reference, Source]:
    zotero = ZoteroReference(
        server_id="test",
        item_key="ITEM",
        original_attachment_key="ORIGINAL",
        original_sha256="a" * 64,
        clean_attachment_key="CLEAN",
        clean_sha256="b" * 64,
    )
    payload = Source(
        **article.source.model_dump(
            exclude={"bibliography", "original_path", "archive_path", "zotero"}
        ),
        zotero=zotero,
    )
    with application.database.transaction() as ledger:
        reference = ledger.append("pilot", "source", payload, "test")
    return reference, payload


@pytest.fixture
def snapshot(source: tuple[Reference, Source]) -> DocumentSnapshot:
    reference, payload = source
    return DocumentSnapshot(
        source=reference,
        zotero=payload.zotero,
        pdf_sha256=payload.sha256,
        blocks=[DocumentBlock(id="text", kind="text", text="Original wording.", page=1)],
        page_sizes={1: (200, 300)},
        clean_pages={1: 1},
        method=extraction.CONFIGURATION,
    )


def job_state(ledger: Ledger, request_hash: str) -> dict[str, object]:
    row = ledger.connection.execute(
        "SELECT state,attempts,error FROM extraction_jobs WHERE request_hash=%s",
        (request_hash,),
    ).fetchone()
    assert row is not None
    return row


def test_request_deduplicates_and_processing_does_not_write_knowledge(
    application: Knowledge, source: tuple[Reference, Source], snapshot: DocumentSnapshot
) -> None:
    with application.database.transaction() as ledger:
        before = ledger.connection.execute(
            "SELECT * FROM revisions ORDER BY entity_id,revision"
        ).fetchall()
        request_hash = extraction.request_extraction(ledger, source[0])
        assert extraction.request_extraction(ledger, source[0]) == request_hash
        job = extraction.claim_job(ledger)
        assert job is not None
        assert job.request_hash == request_hash
        assert extraction.claim_job(ledger) is None
        extraction.save_snapshot(ledger, request_hash, snapshot)
        assert extraction.request_extraction(ledger, source[0]) == request_hash
        assert extraction.claim_job(ledger) is None
        assert job_state(ledger, request_hash)["state"] == "succeeded"
        after = ledger.connection.execute(
            "SELECT * FROM revisions ORDER BY entity_id,revision"
        ).fetchall()
        assert after == before


def test_snapshots_pin_exact_source_and_extraction_revisions(
    application: Knowledge,
    source: tuple[Reference, Source],
    snapshot: DocumentSnapshot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with application.database.transaction() as ledger:
        first_request = extraction.request_extraction(ledger, source[0])
        extraction.claim_job(ledger)
        extraction.save_snapshot(ledger, first_request, snapshot)
        second_source = ledger.append("pilot", "source", source[1], "test", source[0])
        assert extraction.get_snapshot(ledger, second_source) is None
        assert extraction.request_extraction(ledger, second_source) != first_request

    monkeypatch.setattr(extraction, "CONFIGURATION", "updated-parser-fixture")
    changed = snapshot.model_copy(deep=True)
    changed.method = extraction.CONFIGURATION
    changed.blocks[0].text = "New extraction wording."
    with application.database.transaction() as ledger:
        second_request = extraction.request_extraction(ledger, source[0])
        ledger.connection.execute(
            "UPDATE extraction_jobs SET state='running' WHERE request_hash=%s", (second_request,)
        )
        extraction.save_snapshot(ledger, second_request, changed)
        historical = extraction.get_snapshot(ledger, source[0], 1)
        current = extraction.get_snapshot(ledger, source[0])
        assert historical is not None and current is not None
        assert historical.blocks[0].text == "Original wording."
        assert current.revision == 2
        assert extraction.get_snapshot(ledger, second_source) is None


@pytest.mark.parametrize(
    "statement", ["UPDATE document_snapshots SET revision=99", "DELETE FROM document_snapshots"]
)
def test_snapshot_rows_are_immutable(
    application: Knowledge,
    source: tuple[Reference, Source],
    snapshot: DocumentSnapshot,
    statement: LiteralString,
) -> None:
    with application.database.transaction() as ledger:
        request_hash = extraction.request_extraction(ledger, source[0])
        extraction.claim_job(ledger)
        extraction.save_snapshot(ledger, request_hash, snapshot)
    with (
        pytest.raises(psycopg.errors.RaiseException, match="append-only"),
        application.database.transaction() as ledger,
    ):
        ledger.connection.execute(statement)


def test_interrupted_jobs_recover_only_within_attempt_budget(
    application: Knowledge, source: tuple[Reference, Source]
) -> None:
    with application.database.transaction() as ledger:
        request_hash = extraction.request_extraction(ledger, source[0])
        first = extraction.claim_job(ledger)
        assert first is not None and first.attempts == 1
        extraction.recover_jobs(ledger)
        assert job_state(ledger, request_hash)["state"] == "queued"
        second = extraction.claim_job(ledger)
        assert second is not None and second.attempts == 2
        extraction.recover_jobs(ledger)
        assert job_state(ledger, request_hash)["state"] == "failed"
        assert extraction.claim_job(ledger) is None


@pytest.mark.parametrize("transient", [False, True])
def test_failures_retry_transient_jobs_once(
    application: Knowledge, source: tuple[Reference, Source], transient: bool
) -> None:
    with application.database.transaction() as ledger:
        request_hash = extraction.request_extraction(ledger, source[0])
        extraction.claim_job(ledger)
        extraction.fail_job(ledger, request_hash, "Tool failure", transient)
        assert job_state(ledger, request_hash)["state"] == ("queued" if transient else "failed")
        if transient:
            extraction.claim_job(ledger)
            extraction.fail_job(ledger, request_hash, "Repeated timeout", True)
            assert job_state(ledger, request_hash)["state"] == "failed"
        assert extraction.claim_job(ledger) is None


@pytest.mark.parametrize("mismatch", ["job", "zotero", "pdf", "missing_job", "queued"])
def test_snapshot_rejects_mismatched_identity_or_unclaimed_job(
    application: Knowledge,
    source: tuple[Reference, Source],
    snapshot: DocumentSnapshot,
    mismatch: str,
) -> None:
    with application.database.transaction() as ledger:
        request_hash = extraction.request_extraction(ledger, source[0])
        if mismatch != "queued":
            extraction.claim_job(ledger)
        if mismatch == "job":
            snapshot.source = ledger.append("pilot", "source", source[1], "test", source[0])
        if mismatch == "zotero":
            snapshot.zotero = snapshot.zotero.model_copy(
                update={"original_attachment_key": "WRONG"}
            )
        if mismatch == "pdf":
            snapshot.pdf_sha256 = "f" * 64
        if mismatch == "missing_job":
            request_hash = "not-a-job"
        with pytest.raises(ValueError):
            extraction.save_snapshot(ledger, request_hash, snapshot)
        row = ledger.connection.execute(
            "SELECT count(*) AS total FROM document_snapshots"
        ).fetchone()
        assert row is not None
        assert row["total"] == 0


def test_failure_cannot_overwrite_completed_job(
    application: Knowledge, source: tuple[Reference, Source], snapshot: DocumentSnapshot
) -> None:
    with application.database.transaction() as ledger:
        request_hash = extraction.request_extraction(ledger, source[0])
        extraction.claim_job(ledger)
        extraction.save_snapshot(ledger, request_hash, snapshot)
        extraction.fail_job(ledger, request_hash, "Late failure", True)
        extraction.recover_jobs(ledger)
        assert job_state(ledger, request_hash)["state"] == "succeeded"


def write_pdf(path: Path, shades: list[float]) -> Path:
    writer = PdfWriter()
    for shade in shades:
        page = writer.add_blank_page(width=200, height=300)
        content = DecodedStreamObject()
        content.set_data(f"{shade} g 20 20 160 260 re f".encode())
        page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(path)
    return path


@pytest.mark.parametrize("remove_cover", [False, True])
def test_page_map_verifies_renders_for_identical_or_cover_removed_pdfs(
    tmp_path: Path, remove_cover: bool
) -> None:
    original = write_pdf(tmp_path / "original.pdf", [0.1, 0.4, 0.8])
    clean = write_pdf(tmp_path / "clean.pdf", [0.4, 0.8] if remove_cover else [0.1, 0.4, 0.8])
    expected = {2: 1, 3: 2} if remove_cover else {1: 1, 2: 2, 3: 3}
    assert verified_page_map(original, clean) == expected


def test_page_map_rejects_swapped_pages_with_equal_page_counts(tmp_path: Path) -> None:
    original = write_pdf(tmp_path / "original.pdf", [0.1, 0.4, 0.8])
    swapped = write_pdf(tmp_path / "swapped.pdf", [0.1, 0.8, 0.4])
    with pytest.raises(ValueError, match="rendered pages differ"):
        verified_page_map(original, swapped)


def test_page_map_rejects_unexplained_removed_pages(tmp_path: Path) -> None:
    original = write_pdf(tmp_path / "original.pdf", [0.1, 0.4, 0.8])
    truncated = write_pdf(tmp_path / "truncated.pdf", [0.8])
    with pytest.raises(ValueError, match="explicit verified page map"):
        verified_page_map(original, truncated)


def test_import_preparation_resumes_persisted_source_without_repeating_extraction(
    source: tuple[Reference, Source], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge.source_workflows import source_import

    prepared = source_import.PreparedImport(source=source[1], extractions=[])
    document = source_import.ImportDocument(path="source.pdf")
    monkeypatch.setattr(source_import, "prepare_document", lambda *args: prepared)
    assert source_import.load_prepared_document(document, "pilot", tmp_path) == prepared
    monkeypatch.delattr(source_import, "prepare_document")
    assert source_import.load_prepared_document(document, "pilot", tmp_path) == prepared
