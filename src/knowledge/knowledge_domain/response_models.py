"""Describe JSON responses shared by command and HTTP adapters."""

from typing import TypedDict

from pydantic import JsonValue


class RecordResponse(TypedDict):
    """Expose a serialized record, review status and pinned dependencies."""

    record: dict[str, JsonValue]
    status: str
    dependencies: list[dict[str, JsonValue]]


class RecordSummary(TypedDict):
    """Expose the serialized fields needed for a search result."""

    reference: dict[str, JsonValue]
    kind: str
    status: str
    summary: dict[str, JsonValue]


class SearchResponse(TypedDict):
    """Return a bounded record search page and its total size."""

    total: int
    offset: int
    records: list[RecordSummary]


class PlainPassage(TypedDict):
    """Expose a source page from the original text snapshot."""

    source: dict[str, JsonValue]
    page: int
    text: str


class StructuredPassage(TypedDict):
    """Expose located blocks and the constraints for their evidentiary use."""

    source: dict[str, JsonValue]
    page: int
    extraction_revision: int
    blocks: list[dict[str, JsonValue]]
    evidence_rule: str


class ReceiptResponse(TypedDict):
    """Expose the accepted request identifier and its serialized references."""

    request_id: str
    result: list[dict[str, JsonValue]]
