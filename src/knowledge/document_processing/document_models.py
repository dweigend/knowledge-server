"""Define immutable document snapshots, locations, blocks, and annotations.

The contracts stay independent of extraction providers and presentation formats
so stored snapshots remain readable when tools change.
"""

from typing import Literal

from pydantic import ConfigDict, Field

from knowledge.knowledge_domain import knowledge_record_models as models


class DocumentLocation(models.Contract):
    """Locate content on an original PDF page in top-left PDF-point coordinates."""

    page: int = Field(ge=1)
    region: tuple[float, float, float, float] | None = None


class CellText(models.Contract):
    """Preserve plain, superscript and subscript text inside one table cell."""

    model_config = ConfigDict(str_strip_whitespace=False)

    text: str
    script: Literal["normal", "sup", "sub"] = "normal"


class TableCell(models.Contract):
    """Preserve a table cell's zero-based position, spans and header role."""

    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    text: str
    runs: list[CellText] = Field(default_factory=list)
    header: bool = False
    row_header: bool = False


class DocumentBlock(models.Contract):
    """Keep one ordered source block and its extraction limitations."""

    id: str
    kind: str
    text: str = ""
    heading_level: int = 0
    page: int | None = Field(default=None, ge=1)
    region: tuple[float, float, float, float] | None = None
    locations: list[DocumentLocation] = Field(default_factory=list)
    label: str = ""
    caption: str = ""
    caption_ids: list[str] = Field(default_factory=list)
    footnote_ids: list[str] = Field(default_factory=list)
    cells: list[TableCell] = Field(default_factory=list)
    rows: int = 0
    columns: int = 0
    issues: list[str] = Field(default_factory=list)
    method: str = "docling"


class DocumentRelationship(models.Contract):
    """Record a located affiliation or citation link without guessing unresolved targets."""

    kind: Literal["affiliation", "citation"]
    from_id: str
    to_id: str
    text: str = ""
    verified: bool = False
    origin_text: str = ""
    target_text: str = ""


class DocumentSnapshot(models.Contract):
    """Pin one extraction revision to its source and Zotero PDF version."""

    source: models.Reference
    zotero: models.ZoteroReference
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: int = Field(default=1, ge=1)
    blocks: list[DocumentBlock]
    page_sizes: dict[int, tuple[float, float]]
    clean_pages: dict[int, int]
    method: str
    issues: list[str] = Field(default_factory=list)
    relationships: list[DocumentRelationship] = Field(default_factory=list)
    candidates: list[DocumentBlock] = Field(default_factory=list)
    annotation: str = ""


class DocumentAnnotation(models.Contract):
    """Classify inspected source blocks and link exact document text spans."""

    source: models.Reference
    expected_revision: int = Field(ge=1)
    block_kinds: dict[str, Literal["abstract", "reference", "text", "heading", "furniture"]]
    block_issues: dict[str, list[str]] = Field(default_factory=dict)
    relationships: list[DocumentRelationship]
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)
