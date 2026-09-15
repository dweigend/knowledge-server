"""Import an explicit PDF manifest through Zotero and candidate reconciliation."""

import hashlib
import json
import tempfile
from collections.abc import Callable
from pathlib import Path

from pydantic import Field

from knowledge import sources
from knowledge.application import Knowledge
from knowledge.contracts import (
    Bibliography,
    Contract,
    ExtractedClaim,
    Reference,
    Source,
    Text,
    ZoteroReference,
)
from knowledge.generation import ModelConfiguration, generate
from knowledge.ingestion import extract_pdf_pages, locate_passage, remove_curator_cover
from knowledge.prompt_registry import operation_configuration
from knowledge.reconciliation import reconcile_claim
from knowledge.run_log import record_event
from knowledge.zotero import import_sources

PAGE_BUDGET = 65000
IMPORT_ACTOR = "hermes:import-v2"


class ArticleExtraction(Contract):
    """Extract a bounded contribution without requiring a new note per document."""

    bibliography: Bibliography
    claims: list[ExtractedClaim] = Field(max_length=1)
    study_group: Text
    overlap: Text
    warnings: list[str]


class ImportDocument(Contract):
    """Name an explicit server PDF and its manually verified cover treatment."""

    path: str
    remove_cover: bool = False


class RegisterSource(Contract):
    """Register the verified Zotero source independently of its optional contributions."""

    source: Source


def page_chunks(pages: list[str]) -> list[dict]:
    """Partition every evidence page without losing original PDF numbering."""
    chunks: list[dict] = []
    current: dict[int, str] = {}
    characters = 0
    for number, text in enumerate(pages, 1):
        if text == "[Curator cover excluded from evidence]":
            continue
        if len(text) > PAGE_BUDGET:
            raise ValueError(f"PDF page {number} exceeds extraction budget")
        if current and characters + len(text) > PAGE_BUDGET:
            chunks.append(current)
            current, characters = {}, 0
        current[number] = text
        characters += len(text)
    if current:
        chunks.append(current)
    return chunks


def validate_extraction(extraction: ArticleExtraction, pages: list[str], supplied: dict) -> None:
    """Restore exact quote typography and reject quotations outside the supplied pages."""
    for claim in extraction.claims:
        claimed_page = claim.page
        claim.page, claim.quote = locate_passage(pages, claimed_page, claim.quote)
        if claim.page not in supplied:
            raise ValueError("Quote is outside the supplied chunk")
        if claimed_page != claim.page:
            extraction.warnings.append(f"Corrected PDF page {claimed_page} to {claim.page}")


def validate_import_proposal(
    proposal: ArticleExtraction,
    pages: list[str],
    supplied: dict,
    validate: Callable[[ArticleExtraction], None] | None,
) -> None:
    """Apply exact import citation checks and optional additional source-boundary checks."""
    validate_extraction(proposal, pages, supplied)
    if validate is not None:
        validate(proposal)


def extract_document(
    pages: list[str],
    run_directory: Path,
    *,
    instructions: str | None = None,
    configuration: ModelConfiguration | None = None,
    cancelled: Callable[[], bool] | None = None,
    blocks_packet: dict | None = None,
    validate: Callable[[ArticleExtraction], None] | None = None,
) -> list[ArticleExtraction]:
    """Extract one inspectable contribution per complete page chunk."""
    if instructions is None:
        instructions, default_configuration = operation_configuration("formulate_claims")
        configuration = configuration or default_configuration
    prompt = instructions
    proposals = []
    for chunk in page_chunks(pages):
        packet = json.dumps(
            {
                "pages": chunk,
                "known_bibliography": proposals[0].bibliography.model_dump(mode="json")
                if proposals
                else None,
                **({"information_blocks": blocks_packet} if blocks_packet is not None else {}),
            },
            ensure_ascii=False,
        )
        proposal = generate(
            prompt,
            packet,
            ArticleExtraction,
            run_directory / "proposals",
            lambda result, supplied=chunk: validate_import_proposal(
                result, pages, supplied, validate
            ),
            configuration=configuration,
            cancelled=cancelled,
        )
        record_event(
            run_directory,
            "extraction",
            pages=list(chunk),
            claims=len(proposal.claims),
            warnings=proposal.warnings,
        )
        proposals.append(proposal)
    return proposals


def merge_extracted_metadata(
    extractions: list[ArticleExtraction], run_directory: Path
) -> Bibliography:
    """Fill metadata gaps from later chunks and log conflicts without overwriting known fields."""
    merged = {}
    for field in ("title", "authors", "year", "doi", "url"):
        values = distinct_metadata_values(extractions, field)
        merged[field] = values[0] if values else ([] if field == "authors" else "")
        if len(values) > 1:
            record_event(
                run_directory,
                "metadata_conflict",
                field=field,
                retained=values[0],
                distinct_values=values,
            )
    return Bibliography.model_validate(merged)


def distinct_metadata_values(extractions: list[ArticleExtraction], field: str) -> list:
    """Keep distinct nonempty values in source-chunk order."""
    values = []
    for extraction in extractions:
        value = getattr(extraction.bibliography, field)
        if value and value not in values:
            values.append(value)
    return values


def prepare_document(
    document: ImportDocument, batch_id: str, run_directory: Path
) -> tuple[Source, list[ArticleExtraction]]:
    """Prepare temporary PDF derivatives and transfer ownership to verified Zotero storage."""
    original = Path(document.path)
    pages = extract_pdf_pages(original)
    if document.remove_cover:
        pages[0] = "[Curator cover excluded from evidence]"
    extractions = extract_document(pages, run_directory)
    bibliography = merge_extracted_metadata(extractions, run_directory)
    zotero = store_document_pdfs(document, bibliography, batch_id)
    source = Source(
        zotero=zotero,
        sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
        pages=pages,
        extraction_method="pdftotext reading-order; v3",
        extraction_warnings=[warning for result in extractions for warning in result.warnings],
        study_group=extractions[0].study_group,
        overlap=extractions[0].overlap,
    )
    return source, extractions


def store_document_pdfs(
    document: ImportDocument, bibliography: Bibliography, batch_id: str
) -> ZoteroReference:
    """Transfer PDF ownership to Zotero and discard a temporary cover-free derivative."""
    original = Path(document.path)
    if not document.remove_cover:
        return import_sources(bibliography, original, original, batch_id)
    with tempfile.TemporaryDirectory(prefix="knowledge-import-") as temporary:
        clean = Path(temporary) / "clean.pdf"
        remove_curator_cover(original, clean)
        return import_sources(bibliography, original, clean, batch_id)


def import_document(
    application: Knowledge, batch_id: str, document: ImportDocument, run_directory: Path
) -> None:
    """Resume preparation, source registration and contribution reconciliation in order."""
    digest = hashlib.sha256(Path(document.path).read_bytes()).hexdigest()
    document_directory = run_directory / digest
    if document_completed(application, batch_id, digest):
        (document_directory / "prepared.json").unlink(missing_ok=True)
        record_event(run_directory, "document_already_completed", sha256=digest)
        return
    source, extractions = load_prepared_document(document, batch_id, document_directory)
    reference = register_document_source(application, batch_id, digest, source)
    accept_contributions(application, batch_id, reference, extractions, document_directory, digest)
    complete_document(application, batch_id, digest, source, reference, document, run_directory)


def load_prepared_document(
    document: ImportDocument, batch_id: str, document_directory: Path
) -> tuple[Source, list[dict]]:
    """Resume the transient preparation snapshot or create it before database writes."""
    document_directory.mkdir(parents=True, exist_ok=True)
    prepared_path = document_directory / "prepared.json"
    if not prepared_path.exists():
        source, extractions = prepare_document(document, batch_id, document_directory)
        prepared_path.write_text(
            json.dumps(
                {
                    "source": source.model_dump(mode="json"),
                    "extractions": [result.model_dump(mode="json") for result in extractions],
                }
            )
        )
    prepared = json.loads(prepared_path.read_text())
    return Source.model_validate(prepared["source"]), prepared["extractions"]


def register_document_source(
    application: Knowledge, batch_id: str, digest: str, source: Source
) -> Reference:
    """Register the source through its stable receipt before accepting contributions."""
    references = application.database.command(
        f"{batch_id}:source:{digest}",
        batch_id,
        "register_source",
        RegisterSource(source=source),
        IMPORT_ACTOR,
        lambda ledger: [sources.register(ledger, batch_id, source, IMPORT_ACTOR)],
    )
    return references[0]


def complete_document(
    application: Knowledge,
    batch_id: str,
    digest: str,
    source: Source,
    reference: Reference,
    document: ImportDocument,
    run_directory: Path,
) -> None:
    """Commit the completion receipt before removing temporary state and reporting success."""
    application.database.command(
        f"{batch_id}:document:{digest}",
        batch_id,
        "complete_import",
        RegisterSource(source=source),
        IMPORT_ACTOR,
        lambda ledger: [reference],
    )
    (run_directory / digest / "prepared.json").unlink()
    record_event(
        run_directory,
        "document_completed",
        path=document.path,
        sha256=digest,
        source=reference.model_dump(mode="json"),
    )


def accept_contributions(
    application: Knowledge,
    batch_id: str,
    source: Reference,
    extractions: list[dict],
    run_directory: Path,
    digest: str,
) -> None:
    """Keep stable per-chunk identities while adding or reusing claims."""
    for chunk_index, serialized in enumerate(extractions):
        extraction = ArticleExtraction.model_validate(serialized)
        for claim_index, proposal in enumerate(extraction.claims):
            request_id = f"{batch_id}:contribution:{digest}:{chunk_index}:{claim_index}"
            reconcile_claim(application, batch_id, source, proposal, run_directory, request_id)


def import_manifest(
    application: Knowledge, batch_id: str, manifest: Path, run_directory: Path
) -> None:
    """Import explicitly selected documents and log any failure before stopping."""
    documents = [ImportDocument.model_validate(entry) for entry in json.loads(manifest.read_text())]
    for document in documents:
        record_event(run_directory, "document_started", path=document.path)
        try:
            import_document(application, batch_id, document, run_directory)
        except Exception as error:
            record_event(
                run_directory,
                "document_failed",
                path=document.path,
                error_type=type(error).__name__,
                error=str(error),
            )
            raise


def document_completed(application: Knowledge, batch_id: str, digest: str) -> bool:
    """Recognize completed imports and older accepted sources without skipping partial imports."""
    with application.database.transaction() as ledger:
        if ledger.get_receipt(f"{batch_id}:document:{digest}"):
            return True
        if ledger.get_receipt(f"{batch_id}:source:{digest}"):
            return False
        return any(
            isinstance(record.payload, Source) and record.payload.sha256 == digest
            for record in ledger.list(batch_id, "source")
        )
