"""Translate Marker page output into shared document blocks.

The parser preserves raster-page regions and tables so Marker results can be
reconciled with the primary Docling extraction.
"""

from collections.abc import Mapping
from html.parser import HTMLParser
from typing import Literal, override

from knowledge.document_processing import document_models
from knowledge.document_processing.extraction_input_models import MarkerNode


class TableParser(HTMLParser):
    """Read explicit HTML cells without guessing missing values or correcting text."""

    def __init__(self) -> None:
        """Initialize an empty table grid and plain-text accumulator."""
        super().__init__(convert_charrefs=True)
        self.cells: list[document_models.TableCell] = []
        self.row = -1
        self.column = 0
        self.occupied: set[tuple[int, int]] = set()
        self.current: document_models.TableCell | None = None
        self.text: list[str] = []
        self.scripts: list[Literal["normal", "sup", "sub"]] = []

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Keep row boundaries and explicit cell spans from the extraction."""
        if tag in {"sup", "sub"} and self.current is not None:
            self.scripts.append("sup" if tag == "sup" else "sub")
            return
        if tag == "tr":
            self.row += 1
            self.column = 0
            return
        if tag not in {"td", "th"}:
            return
        if self.current is not None or self.row < 0:
            raise ValueError("Marker table has invalid cell boundaries")
        attributes = dict(attrs)
        while (self.row, self.column) in self.occupied:
            self.column += 1
        self.current = document_models.TableCell(
            row=self.row,
            column=self.column,
            text="",
            row_span=int(attributes.get("rowspan") or 1),
            column_span=int(attributes.get("colspan") or 1),
            header=tag == "th" and attributes.get("scope") != "row",
            row_header=tag == "th" and attributes.get("scope") == "row",
        )

    @override
    def handle_endtag(self, tag: str) -> None:
        """Finish a cell and reserve every position covered by its spans."""
        if tag in {"sup", "sub"} and self.scripts:
            self.scripts.pop()
            return
        if tag not in {"td", "th"} or self.current is None:
            return
        cell = self.current
        for row in range(cell.row, cell.row + cell.row_span):
            self.occupied.update(
                (row, column) for column in range(cell.column, cell.column + cell.column_span)
            )
        self.cells.append(cell)
        self.column += cell.column_span
        self.current = None
        self.scripts.clear()

    @override
    def handle_data(self, data: str) -> None:
        """Preserve extracted characters, including superscript marker text."""
        self.text.append(data)
        if self.current is None:
            return
        self.current.text += data
        script = self.scripts[-1] if self.scripts else "normal"
        if self.current.runs and self.current.runs[-1].script == script:
            self.current.runs[-1].text += data
            return
        self.current.runs.append(document_models.CellText(text=data, script=script))


def _region(
    polygon: list[list[float]], page_polygon: list[list[float]], page_size: tuple[float, float]
) -> tuple[float, float, float, float]:
    horizontal_scale = page_size[0] / (page_polygon[2][0] - page_polygon[0][0])
    vertical_scale = page_size[1] / (page_polygon[2][1] - page_polygon[0][1])
    left = min(point[0] for point in polygon) - page_polygon[0][0]
    top = min(point[1] for point in polygon) - page_polygon[0][1]
    right = max(point[0] for point in polygon) - page_polygon[0][0]
    bottom = max(point[1] for point in polygon) - page_polygon[0][1]
    return (
        left * horizontal_scale,
        top * vertical_scale,
        right * horizontal_scale,
        bottom * vertical_scale,
    )


def _leaf_nodes(node: MarkerNode) -> list[MarkerNode]:
    if node.block_type == "Table" or not node.children:
        return [node]
    return [leaf for child in (node.children or []) for leaf in _leaf_nodes(child)]


def _block(
    node: MarkerNode,
    original_page: int,
    page_polygon: list[list[float]],
    page_size: tuple[float, float],
) -> document_models.DocumentBlock:
    if node.id is None:
        raise ValueError("Marker content block is missing its ID")
    html = node.html
    text_parser = TableParser()
    text_parser.feed(html)
    cells = []
    if node.block_type == "Table":
        text_parser.close()
        if text_parser.current is not None:
            raise ValueError("Marker table has an unclosed cell")
        cells = text_parser.cells
    polygon = node.polygon
    region = _region(polygon, page_polygon, page_size) if polygon else None
    issues = []
    if "<content-ref" in html:
        issues.append("Marker output contains unresolved content references")
    if not cells and ("<sup" in html or "<sub" in html):
        issues.append("Superscript or subscript flattened into text; verify markers in PDF")
    return document_models.DocumentBlock(
        id=f"marker:{original_page}:{node.id}",
        kind=node.block_type.lower(),
        text="".join(text_parser.text),
        page=original_page,
        region=region,
        locations=[document_models.DocumentLocation(page=original_page, region=region)],
        cells=cells,
        rows=max((cell.row + cell.row_span for cell in cells), default=0),
        columns=max((cell.column + cell.column_span for cell in cells), default=0),
        method="marker-raster",
        issues=issues,
    )


def marker_blocks(
    document: MarkerNode | Mapping[str, object], original_page: int, page_size: tuple[float, float]
) -> list[document_models.DocumentBlock]:
    """Convert one raster page, restoring original-page numbering and PDF coordinates."""
    document = MarkerNode.model_validate(document)
    pages = [document] if document.block_type == "Page" else (document.children or [])
    if len(pages) != 1 or pages[0].block_type != "Page":
        raise ValueError("Marker comparison requires exactly one raster page")
    page = pages[0]
    if not page.polygon:
        raise ValueError("Marker page is missing its polygon")
    return [
        _block(node, original_page, page.polygon, page_size)
        for child in (page.children or [])
        for node in _leaf_nodes(child)
    ]
