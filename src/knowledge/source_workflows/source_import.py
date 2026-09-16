"""Import explicit PDF manifests through Zotero and knowledge reconciliation.

The workflow prepares metadata, stores PDFs, proposes contributions, and accepts
validated results through application commands.
"""

import hashlib
import tempfile
from pathlib import Path

from pydantic import TypeAdapter

from knowledge.document_processing import pdf_text_extraction
from knowledge.knowledge_base import knowledge_service, source_records
from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.literature import zotero_client
from knowledge.runtime_support import workflow_event_log
from knowledge.source_workflows import article_claim_extraction, claim_reconciliation

IMPORT_ACTOR = "hermes:import-v2"


class ImportDocument(models.Contract):
    """Name an explicit server PDF and its manually verified cover treatment."""

    path: str
    remove_cover: bool = False


class RegisterSource(models.Contract):
    """Register the verified Zotero source independently of its optional contributions."""

    source: models.Source


class PreparedImport(models.Contract):
    """Persist one resumable source and its validated extraction proposals."""

    source: models.Source
    extractions: list[article_claim_extraction.ArticleExtraction]


def prepare_document(
    document: ImportDocument, batch_id: str, run_directory: Path
) -> tuple[models.Source, list[article_claim_extraction.ArticleExtraction]]:
    """Prepare temporary PDF derivatives and transfer ownership to verified Zotero storage."""
    original = Path(document.path)
    pages = pdf_text_extraction.extract_pdf_pages(original)
    if document.remove_cover:
        pages[0] = "[Curator cover excluded from evidence]"
    extractions = article_claim_extraction.extract_document(pages, run_directory)
    bibliography = article_claim_extraction.merge_extracted_metadata(extractions, run_directory)
    zotero = store_document_pdfs(document, bibliography, batch_id)
    source = models.Source(
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
    document: ImportDocument, bibliography: models.Bibliography, batch_id: str
) -> models.ZoteroReference:
    """Transfer PDF ownership to Zotero and discard a temporary cover-free derivative."""
    original = Path(document.path)
    if not document.remove_cover:
        return zotero_client.import_sources(bibliography, original, original, batch_id)
    with tempfile.TemporaryDirectory(prefix="knowledge-import-") as temporary:
        clean = Path(temporary) / "clean.pdf"
        pdf_text_extraction.remove_curator_cover(original, clean)
        return zotero_client.import_sources(bibliography, original, clean, batch_id)


def import_document(
    application: knowledge_service.Knowledge,
    batch_id: str,
    document: ImportDocument,
    run_directory: Path,
) -> None:
    """Resume preparation, source registration and contribution reconciliation in order."""
    digest = hashlib.sha256(Path(document.path).read_bytes()).hexdigest()
    document_directory = run_directory / digest
    if document_completed(application, batch_id, digest):
        (document_directory / "prepared.json").unlink(missing_ok=True)
        workflow_event_log.record_event(run_directory, "document_already_completed", sha256=digest)
        return
    source, extractions = load_prepared_document(document, batch_id, document_directory)
    reference = register_document_source(application, batch_id, digest, source)
    accept_contributions(application, batch_id, reference, extractions, document_directory, digest)
    complete_document(application, batch_id, digest, source, reference, document, run_directory)


def load_prepared_document(
    document: ImportDocument, batch_id: str, document_directory: Path
) -> tuple[models.Source, list[article_claim_extraction.ArticleExtraction]]:
    """Resume the transient preparation snapshot or create it before database writes."""
    document_directory.mkdir(parents=True, exist_ok=True)
    prepared_path = document_directory / "prepared.json"
    if not prepared_path.exists():
        source, extractions = prepare_document(document, batch_id, document_directory)
        prepared_path.write_text(
            PreparedImport(source=source, extractions=extractions).model_dump_json()
        )
    prepared = PreparedImport.model_validate_json(prepared_path.read_text())
    return prepared.source, prepared.extractions


def register_document_source(
    application: knowledge_service.Knowledge,
    batch_id: str,
    digest: str,
    source: models.Source,
) -> models.Reference:
    """Register the source through its stable receipt before accepting contributions."""
    references = application.database.command(
        f"{batch_id}:source:{digest}",
        batch_id,
        "register_source",
        RegisterSource(source=source),
        IMPORT_ACTOR,
        lambda ledger: [source_records.register(ledger, batch_id, source, IMPORT_ACTOR)],
    )
    return references[0]


def complete_document(
    application: knowledge_service.Knowledge,
    batch_id: str,
    digest: str,
    source: models.Source,
    reference: models.Reference,
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
    workflow_event_log.record_event(
        run_directory,
        "document_completed",
        path=document.path,
        sha256=digest,
        source=reference.model_dump(mode="json"),
    )


def accept_contributions(
    application: knowledge_service.Knowledge,
    batch_id: str,
    source: models.Reference,
    extractions: list[article_claim_extraction.ArticleExtraction],
    run_directory: Path,
    digest: str,
) -> None:
    """Keep stable per-chunk identities while adding or reusing claims."""
    for chunk_index, extraction in enumerate(extractions):
        for claim_index, proposal in enumerate(extraction.claims):
            request_id = f"{batch_id}:contribution:{digest}:{chunk_index}:{claim_index}"
            claim_reconciliation.reconcile_claim(
                application, batch_id, source, proposal, run_directory, request_id
            )


def import_manifest(
    application: knowledge_service.Knowledge,
    batch_id: str,
    manifest: Path,
    run_directory: Path,
) -> None:
    """Import explicitly selected documents and log any failure before stopping."""
    documents = TypeAdapter(list[ImportDocument]).validate_json(manifest.read_text())
    for document in documents:
        workflow_event_log.record_event(run_directory, "document_started", path=document.path)
        try:
            import_document(application, batch_id, document, run_directory)
        except Exception as error:
            workflow_event_log.record_event(
                run_directory,
                "document_failed",
                path=document.path,
                error_type=type(error).__name__,
                error=str(error),
            )
            raise


def document_completed(
    application: knowledge_service.Knowledge, batch_id: str, digest: str
) -> bool:
    """Recognize completed imports and older accepted sources without skipping partial imports."""
    with application.database.transaction() as ledger:
        if ledger.get_receipt(f"{batch_id}:document:{digest}"):
            return True
        if ledger.get_receipt(f"{batch_id}:source:{digest}"):
            return False
        return any(
            isinstance(record.payload, models.Source) and record.payload.sha256 == digest
            for record in ledger.list(batch_id, "source")
        )
