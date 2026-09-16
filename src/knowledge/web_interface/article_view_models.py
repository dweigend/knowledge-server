"""Describe template projections without changing document or knowledge contracts."""

from typing import NotRequired, TypedDict

from markupsafe import Markup

from knowledge.document_processing import document_models
from knowledge.document_processing.extraction_input_models import ExtractionJob
from knowledge.knowledge_domain import knowledge_record_models as models


class CitationView(TypedDict):
    """Present available citation metadata or a visible retrieval error."""

    title: str
    error: NotRequired[str]
    authors: NotRequired[list[str]]
    year: NotRequired[str]
    venue: NotRequired[str]
    version: NotRequired[str]
    doi_url: NotRequired[str]
    publisher_url: NotRequired[str]
    text: NotRequired[str]
    bibtex: NotRequired[str]
    metadata_revision: NotRequired[int | None]
    zotero_url: NotRequired[str]


class KnowledgeEntry(TypedDict):
    """Label a related knowledge record and its overview eligibility."""

    record: models.Record
    title: str
    overview: bool


class BlockLocationView(TypedDict):
    """Link one observed block location to its source PDF page."""

    page: int
    url: str


class BlockView(TypedDict):
    """Present one stored document block with safe rendered links."""

    block: document_models.DocumentBlock
    heading_level: int
    pdf_url: str
    html_text: Markup
    locations: list[BlockLocationView]
    clean_url: str
    table_rows: list[list[document_models.TableCell]]


class RelationshipView(TypedDict):
    """Resolve a stored relationship to its optional endpoint blocks."""

    relationship: document_models.DocumentRelationship
    origin: document_models.DocumentBlock | None
    target: document_models.DocumentBlock | None


class OutlineEntry(TypedDict):
    """Keep recursive heading navigation linked to document blocks."""

    block: document_models.DocumentBlock
    children: list["OutlineEntry"]


class ArticleView(TypedDict):
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
