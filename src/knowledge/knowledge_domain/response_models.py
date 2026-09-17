"""Describe validated responses shared by command and HTTP adapters."""

from pydantic import Field, JsonValue

from knowledge.knowledge_domain import knowledge_record_models as models


class HealthResponse(models.Contract):
    """Report successful database connectivity."""

    status: str


class RecordResponse(models.Contract):
    """Expose a record, review status and pinned dependencies."""

    record: models.Record
    status: str
    dependencies: list[models.Reference]


class RecordSummary(models.Contract):
    """Expose the fields needed for a search result."""

    reference: models.Reference
    kind: models.Kind
    status: str
    summary: dict[str, JsonValue]


class SearchResponse(models.Contract):
    """Return a bounded record search page and its total size."""

    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    records: list[RecordSummary]


class PlainPassage(models.Contract):
    """Expose a source page from the original text snapshot."""

    source: models.Reference
    page: int = Field(ge=1)
    text: str


class ReceiptResponse(models.Contract):
    """Expose an accepted request identifier and its references."""

    request_id: str
    result: list[models.Reference]
