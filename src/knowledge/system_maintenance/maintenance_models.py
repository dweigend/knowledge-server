"""Describe migration and restore reports with their database query rows."""

from typing import Literal, NotRequired, TypedDict

from pydantic import BaseModel

from knowledge.knowledge_domain.knowledge_record_models import Kind


class RevisionCount(TypedDict):
    """Count stored revisions for one domain record kind."""

    kind: Kind
    count: int


class DatabaseInspection(TypedDict):
    """Summarize decoded records and snapshots in a restored database."""

    current_records_decoded: int
    revision_counts: list[RevisionCount]
    document_snapshots_decoded: int


class RestoreReport(DatabaseInspection):
    """Record file integrity and database restoration verification."""

    files_verified: int
    restored_database: str


class SourceMigration(TypedDict):
    """Report whether a source required a Zotero ownership revision."""

    entity_id: str
    status: Literal["already_migrated", "migrated"]
    revision: NotRequired[int]
    original_pdf: NotRequired[str]
    clean_pdf: NotRequired[str]


class BatchRow(BaseModel):
    """Identify a batch returned by a database query."""

    batch_id: str
