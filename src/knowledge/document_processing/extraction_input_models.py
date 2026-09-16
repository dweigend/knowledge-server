"""Validate provider document exports before interpreting their structure."""

from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, AliasPath, BaseModel, Field


class DoclingReference(BaseModel):
    """Identify another node in a Docling export."""

    ref: str = Field(alias="$ref")


class DoclingBounds(BaseModel):
    """Retain provider coordinates and their declared origin."""

    left: float = Field(alias="l")
    top: float = Field(alias="t")
    right: float = Field(alias="r")
    bottom: float = Field(alias="b")
    coord_origin: str | None = None


class DoclingProvenance(BaseModel):
    """Locate a node on one PDF page."""

    page_no: int
    bbox: DoclingBounds | None = None


class DoclingCell(BaseModel):
    """Preserve explicit cell offsets and header evidence."""

    start_row_offset_idx: int
    end_row_offset_idx: int
    start_col_offset_idx: int
    end_col_offset_idx: int
    text: str = ""
    column_header: bool = False
    row_header: bool = False
    row_section: bool = False


class DoclingTable(BaseModel):
    """Describe the exported table grid."""

    num_rows: int = 0
    num_cols: int = 0
    table_cells: list[DoclingCell] = Field(default_factory=list)


class DoclingNode(BaseModel):
    """Keep source text and links independently of document block interpretation."""

    self_ref: str
    label: str = "text"
    text: str = ""
    level: int | None = None
    prov: list[DoclingProvenance] = Field(default_factory=list)
    children: list[DoclingReference] = Field(default_factory=list)
    captions: list[DoclingReference] = Field(default_factory=list)
    footnotes: list[DoclingReference] = Field(default_factory=list)
    references: list[DoclingReference] = Field(default_factory=list)
    data: DoclingTable = Field(default_factory=DoclingTable)


class DoclingBody(BaseModel):
    """Retain ordered references to document body nodes."""

    children: list[DoclingReference] = Field(default_factory=list)


class DoclingPage(BaseModel):
    """Keep source dimensions in PDF points for coordinate conversion."""

    width: float = Field(validation_alias=AliasChoices(AliasPath("size", "width"), "width"))
    height: float = Field(validation_alias=AliasChoices(AliasPath("size", "height"), "height"))


class DoclingDocument(BaseModel):
    """Validate the Docling fields consumed by extraction."""

    schema_name: Literal["DoclingDocument"]
    body: DoclingBody = Field(default_factory=DoclingBody)
    texts: list[DoclingNode] = Field(default_factory=list)
    tables: list[DoclingNode] = Field(default_factory=list)
    pictures: list[DoclingNode] = Field(default_factory=list)
    groups: list[DoclingNode] = Field(default_factory=list)
    pages: dict[str, DoclingPage] = Field(default_factory=dict)


class MarkerNode(BaseModel):
    """Retain recursive Marker blocks, HTML evidence and raster coordinates."""

    id: str | None = None
    block_type: str
    html: str = ""
    polygon: list[list[float]] = Field(default_factory=list)
    children: list["MarkerNode"] | None = None


class ExtractionJob(BaseModel):
    """Identify a claimed extraction job and its pinned source revision."""

    request_hash: str
    source_id: UUID
    source_revision: int
    configuration: str
    state: Literal["queued", "running", "succeeded", "failed"]
    attempts: int
    error: str = ""
