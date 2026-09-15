"""Convert Marker raster-page output into the shared document block contract."""

from html.parser import HTMLParser
from typing import Literal

from knowledge.document_contracts import CellText, DocumentBlock, DocumentLocation, TableCell


class TableParser(HTMLParser):
    """Read explicit HTML cells without guessing missing values or correcting text."""

    def __init__(self) -> None:
        """Initialize an empty table grid and plain-text accumulator."""
        super().__init__(convert_charrefs=True)
        self.cells: list[TableCell] = []
        self.row = -1
        self.column = 0
        self.occupied: set[tuple[int, int]] = set()
        self.current: TableCell | None = None
        self.text: list[str] = []
        self.scripts: list[Literal["normal", "sup", "sub"]] = []

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
        self.current = TableCell(
            row=self.row,
            column=self.column,
            text="",
            row_span=int(attributes.get("rowspan") or 1),
            column_span=int(attributes.get("colspan") or 1),
            header=tag == "th" and attributes.get("scope") != "row",
            row_header=tag == "th" and attributes.get("scope") == "row",
        )

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
        self.current.runs.append(CellText(text=data, script=script))


def parse_table(html: str) -> list[TableCell]:
    """Read table HTML, rejecting incomplete cells rather than losing their content."""
    parser = TableParser()
    parser.feed(html)
    parser.close()
    if parser.current is not None:
        raise ValueError("Marker table has an unclosed cell")
    return parser.cells


def _region(polygon: list, page_polygon: list, page_size: tuple[float, float]) -> tuple:
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


def _leaf_nodes(node: dict) -> list[dict]:
    if node.get("block_type") == "Table" or not node.get("children"):
        return [node]
    return [leaf for child in node["children"] for leaf in _leaf_nodes(child)]


def _block(
    node: dict, original_page: int, page_polygon: list, page_size: tuple[float, float]
) -> DocumentBlock:
    html = node.get("html", "")
    text_parser = TableParser()
    text_parser.feed(html)
    cells = parse_table(html) if node["block_type"] == "Table" else []
    polygon = node.get("polygon")
    region = _region(polygon, page_polygon, page_size) if polygon else None
    issues = []
    if "<content-ref" in html:
        issues.append("Marker output contains unresolved content references")
    if not cells and ("<sup" in html or "<sub" in html):
        issues.append("Superscript or subscript flattened into text; verify markers in PDF")
    return DocumentBlock(
        id=f"marker:{original_page}:{node['id']}",
        kind=node["block_type"].lower(),
        text="".join(text_parser.text),
        page=original_page,
        region=region,
        locations=[DocumentLocation(page=original_page, region=region)],
        cells=cells,
        rows=max((cell.row + cell.row_span for cell in cells), default=0),
        columns=max((cell.column + cell.column_span for cell in cells), default=0),
        method="marker-raster",
        issues=issues,
    )


def marker_blocks(
    document: dict, original_page: int, page_size: tuple[float, float]
) -> list[DocumentBlock]:
    """Convert one raster page, restoring original-page numbering and PDF coordinates."""
    pages = [document] if document.get("block_type") == "Page" else document.get("children", [])
    if len(pages) != 1 or pages[0].get("block_type") != "Page":
        raise ValueError("Marker comparison requires exactly one raster page")
    page = pages[0]
    return [
        _block(node, original_page, page["polygon"], page_size)
        for child in page.get("children", [])
        for node in _leaf_nodes(child)
    ]
