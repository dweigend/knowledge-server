"""Describe source-grounded bibliography recovery and its inspectable audit."""

from typing import Literal

from pydantic import ConfigDict, Field

from knowledge.knowledge_domain.knowledge_record_models import Contract
from knowledge.literature.structured_paper_models import (
    PaperDocument,
    PaperMetadata,
    PaperReference,
)


class BibliographySpan(Contract):
    """Locate exact text using one-based pages and zero-based character offsets."""

    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str


class BibliographyEntry(Contract):
    """Retain detected source text and its original analyzer associations."""

    id: str
    spans: list[BibliographySpan]
    raw: str
    original_ids: list[str] = Field(default_factory=list)


class BibliographyAudit(Contract):
    """Expose recovery changes without claiming bibliographic identity verification."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    status: Literal["consistent", "recovered", "needs_review"]
    original_count: int
    detected_count: int
    resulting_count: int
    entries: list[BibliographyEntry] = Field(default_factory=list)
    missing_entry_ids: list[str] = Field(default_factory=list)
    merged_originals: list[PaperReference] = Field(default_factory=list)
    invalidated_citation_indexes: list[int] = Field(default_factory=list)
    relinked_citation_indexes: list[int] = Field(default_factory=list)
    unresolved_issues: list[str] = Field(default_factory=list)
    model_status: Literal["not_needed", "disabled", "completed", "failed"]


class BibliographyRecoveryResult(Contract):
    """Return the recovered paper with its source-grounded completeness audit."""

    paper: PaperDocument
    report: BibliographyAudit


class ReferenceParsing(Contract):
    """Associate extracted metadata with a supplied exact-source entry identifier."""

    entry_id: str
    metadata: PaperMetadata


class BibliographyParsing(Contract):
    """Propose metadata only for the supplied bibliography source entries."""

    entries: list[ReferenceParsing] = Field(default_factory=list)
