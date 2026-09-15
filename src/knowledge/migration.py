"""Move legacy source ownership to Zotero while preserving every historical revision."""

from pathlib import Path

from knowledge.contracts import LegacySource, Record, Source
from knowledge.storage import Database
from knowledge.zotero import import_sources, verified_pdf


def migrate_sources(database: Database, batch_id: str) -> list[dict]:
    """Append Zotero-backed source revisions only after both PDFs are verified."""
    with database.transaction() as ledger:
        records = ledger.list(batch_id, "source")
    return [migrate_source(database, record) for record in records]


def migrate_source(database: Database, record: Record) -> dict:
    """Keep quote text and page numbering unchanged and leave all archive files intact."""
    source = record.payload
    if not isinstance(source, LegacySource):
        return {"entity_id": str(record.entity_id), "status": "already_migrated"}
    clean_pdf = Path(source.archive_path)
    original_pdf = clean_pdf.with_name("original.pdf")
    reference = import_sources(source.bibliography, original_pdf, clean_pdf, record.batch_id)
    if reference.original_sha256 != source.sha256:
        raise ValueError("Original PDF does not match the registered source checksum")
    replacement = Source(
        **source.model_dump(exclude={"bibliography", "original_path", "archive_path", "zotero"}),
        zotero=reference,
    )
    with database.transaction() as ledger:
        migrated = ledger.append(
            record.batch_id,
            "source",
            replacement,
            "migration:zotero-ownership-v1",
            record.reference(),
        )
    return {
        "entity_id": str(migrated.entity_id),
        "revision": migrated.revision,
        "status": "migrated",
        "original_pdf": str(verified_pdf(reference, "original")),
        "clean_pdf": str(verified_pdf(reference, "clean")),
    }
