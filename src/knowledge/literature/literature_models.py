"""Define literature identities, provider candidates, and citation edges.

These contracts retain external identifiers and occurrence provenance without
creating a second editable literature catalog.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from knowledge.literature import structured_paper_models as papers


class LiteratureMetadata(papers.PaperMetadata):
    """Retain available bibliographic fields without synthesizing missing facts."""

    publisher: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    work_type: str | None = None
    url: str | None = None
    isbn: list[str] = Field(default_factory=list)
    issn: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    """Keep an external candidate separate from accepted bibliographic metadata."""

    model_config = ConfigDict(extra="forbid")
    metadata: LiteratureMetadata
    provider: str
    provider_id: str
    method: Literal["doi", "bibliographic"]


class Resolution(BaseModel):
    """Record the outcome and provenance of one conservative identity check."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["matched", "unmatched", "ambiguous", "error"]
    method: str | None = None
    provider: str | None = None
    checked_at: str
    message: str
    candidates: list[Candidate] = Field(default_factory=list)


class CitationOccurrence(BaseModel):
    """Describe an observed citation edge from a specific uploaded source."""

    model_config = ConfigDict(extra="forbid")
    citing_source_id: str
    occurrence_index: int
    marker: str
    context: str | None = None
    section: str | None = None
    coordinates: str | None = None
    reference_ids: list[str] = Field(default_factory=list)


class LiteratureRecord(BaseModel):
    """Collect one identified work, original references and observed usages."""

    model_config = ConfigDict(extra="forbid")
    id: str
    role: Literal["source", "reference"]
    source_sha256: str
    metadata: LiteratureMetadata
    extracted: list[papers.PaperReference] = Field(default_factory=list)
    reference_ids: list[str] = Field(default_factory=list)
    occurrences: list[CitationOccurrence] = Field(default_factory=list)
    resolution: Resolution
    missing_fields: list[str] = Field(default_factory=list)
