"""Describe validated template projections without changing domain contracts."""

from markupsafe import Markup
from pydantic import BaseModel, ConfigDict, Field

from knowledge.document_processing import document_models
from knowledge.document_processing.extraction_input_models import ExtractionJob
from knowledge.knowledge_domain import knowledge_record_models as models


class ViewContract(BaseModel):
    """Validate transient template data while allowing safe rendering types."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class CitationView(ViewContract):
    """Present available citation metadata or a visible retrieval error."""

    title: str
    error: str = ""
    authors: list[str] = Field(default_factory=list)
    year: str = ""
    venue: str = ""
    version: str = ""
    doi_url: str = ""
    publisher_url: str = ""
    text: str = ""
    bibtex: str = ""
    metadata_revision: int | None = None
    zotero_url: str = ""


class KnowledgeEntry(ViewContract):
    """Label a related knowledge record and its overview eligibility."""

    record: models.Record
    title: str
    overview: bool


class BlockLocationView(ViewContract):
    """Link one observed block location to its source PDF page."""

    page: int
    url: str


class BlockView(ViewContract):
    """Present one stored document block with safe rendered links."""

    block: document_models.DocumentBlock
    heading_level: int
    pdf_url: str
    html_text: Markup
    locations: list[BlockLocationView]
    clean_url: str
    table_rows: list[list[document_models.TableCell]]


class RelationshipView(ViewContract):
    """Resolve a stored relationship to its optional endpoint blocks."""

    relationship: document_models.DocumentRelationship
    origin: document_models.DocumentBlock | None
    target: document_models.DocumentBlock | None


class OutlineEntry(ViewContract):
    """Keep recursive heading navigation linked to document blocks."""

    block: document_models.DocumentBlock
    children: list["OutlineEntry"]


class ArticleView(ViewContract):
    """Compose the template context from individually typed source projections."""

    record: models.Record
    citation: CitationView
    snapshot: document_models.DocumentSnapshot | None
    processing: ExtractionJob | None
    blocks: list[BlockView]
    relationships: list[RelationshipView]
    outline: list[OutlineEntry]
    knowledge: list[KnowledgeEntry]
    history: range
    zotero_url: str
