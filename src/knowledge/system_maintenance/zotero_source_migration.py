"""Migrate legacy source ownership to Zotero without rewriting history.

Each migrated source receives a new revision while every prior record and
reference remains available.
"""

from pathlib import Path

from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.literature import zotero_client
from knowledge.revision_store import postgresql_revision_store
from knowledge.system_maintenance.maintenance_models import SourceMigration


def migrate_sources(
    database: postgresql_revision_store.Database, batch_id: str
) -> list[SourceMigration]:
    """Append Zotero-backed source revisions only after both PDFs are verified."""
    with database.transaction() as ledger:
        records = ledger.list(batch_id, "source")
    return [migrate_source(database, record) for record in records]


def migrate_source(
    database: postgresql_revision_store.Database, record: models.Record
) -> SourceMigration:
    """Keep quote text and page numbering unchanged and leave all archive files intact."""
    source = record.payload
    if not isinstance(source, models.LegacySource):
        return {"entity_id": str(record.entity_id), "status": "already_migrated"}
    clean_pdf = Path(source.archive_path)
    original_pdf = clean_pdf.with_name("original.pdf")
    reference = zotero_client.import_sources(
        source.bibliography,
        original_pdf,
        clean_pdf,
        record.batch_id,
    )
    if reference.original_sha256 != source.sha256:
        raise ValueError("Original PDF does not match the registered source checksum")
    replacement = models.Source(
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
        "original_pdf": str(zotero_client.verified_pdf(reference, "original")),
        "clean_pdf": str(zotero_client.verified_pdf(reference, "clean")),
    }
