"""Define provider-neutral structured paper extraction results.

The contracts represent metadata, references, citations, sections, and document
Markdown independently of GROBID or another analyzer.
"""

from pydantic import BaseModel, ConfigDict, Field


class PaperMetadata(BaseModel):
    """Describe extracted bibliographic fields without inventing missing values."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: str | None = None
    venue: str | None = None
    doi: str | None = None


class PaperReference(PaperMetadata):
    """Retain a bibliography entry and its provider-local citation identifier."""

    id: str
    raw: str | None = None


class PaperCitation(BaseModel):
    """Link an observed citation marker to extracted bibliography identifiers."""

    model_config = ConfigDict(extra="forbid")

    marker: str
    context: str = ""
    section: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    resolved: bool = False
    coordinates: str | None = None


class PaperSection(BaseModel):
    """Retain original section headings and optional PDF bounding boxes."""

    model_config = ConfigDict(extra="forbid")

    title: str
    coordinates: str | None = None


class PaperDocument(BaseModel):
    """Carry normalized Markdown and bibliographic evidence from one provider."""

    model_config = ConfigDict(extra="forbid")

    markdown: str
    metadata: PaperMetadata
    references: list[PaperReference] = Field(default_factory=list)
    citations: list[PaperCitation] = Field(default_factory=list)
    sections: list[PaperSection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provider: str
    provider_version: str | None = None
    raw_document: str | None = None
    raw_format: str = "tei"
