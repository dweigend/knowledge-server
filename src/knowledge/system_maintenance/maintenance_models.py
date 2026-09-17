"""Describe validated migration and restore reports."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from knowledge.knowledge_domain.knowledge_record_models import Kind


class MaintenanceContract(BaseModel):
    """Reject unknown maintenance report fields."""

    model_config = ConfigDict(extra="forbid")


class RevisionCount(MaintenanceContract):
    """Count stored revisions for one domain record kind."""

    kind: Kind
    count: int


class DatabaseInspection(MaintenanceContract):
    """Summarize decoded records and snapshots in a restored database."""

    current_records_decoded: int
    revision_counts: list[RevisionCount]
    document_snapshots_decoded: int


class RestoreReport(DatabaseInspection):
    """Record file integrity and database restoration verification."""

    files_verified: int
    restored_database: str


class SourceMigration(MaintenanceContract):
    """Report whether a source required a Zotero ownership revision."""

    entity_id: str
    status: Literal["already_migrated", "migrated"]
    revision: int | None = Field(default=None, ge=1)
    original_pdf: str | None = None
    clean_pdf: str | None = None
