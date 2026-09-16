"""Translate Docling JSON into ordered document blocks.

The parser retains locations, table structure, reading order, and quality issues
without importing the Docling runtime.
"""

from collections.abc import Iterator, Mapping
from itertools import chain
from typing import Final

from knowledge.document_processing import document_models, extraction_quality
from knowledge.document_processing.extraction_input_models import (
    DoclingCell,
    DoclingDocument,
    DoclingNode,
    DoclingProvenance,
    DoclingTable,
)

SECTION_KINDS: Final[dict[str, str]] = {
    "abstract": "abstract",
    "zusammenfassung": "abstract",
    "references": "reference",
    "bibliography": "reference",
    "literaturverzeichnis": "reference",
}
BLOCK_KINDS: Final[dict[str, str]] = {
    "section_header": "heading",
    "title": "heading",
    "picture": "figure",
    "list_item": "text",
    "page_header": "furniture",
    "page_footer": "furniture",
}


def parse_document(
    document: DoclingDocument | Mapping[str, object],
) -> list[document_models.DocumentBlock]:
    """Preserve body order and recover attached or otherwise unlisted source content."""
    document = DoclingDocument.model_validate(document)

    nodes = _indexed_nodes(document)
    blocks = []
    for node in _ordered_nodes(document, nodes):
        if node.self_ref.startswith("#/groups/"):
            continue
        blocks.append(_parse_block(node, document, nodes))
    _assign_section_kinds(blocks, _body_references(document, nodes))
    return blocks


def _assign_section_kinds(
    blocks: list[document_models.DocumentBlock], body_references: set[str]
) -> None:
    section_kind = ""
    for block in blocks:
        if block.id not in body_references:
            continue
        if block.kind == "heading":
            section_kind = SECTION_KINDS.get(block.text.strip().casefold(), "")
            continue
        if section_kind and block.label in {"text", "paragraph", "list_item"}:
            block.kind = section_kind


def _body_references(
    document: DoclingDocument,
    nodes: dict[str, DoclingNode],
) -> set[str]:
    pending = list(document.body.children)
    references: set[str] = set()
    while pending:
        reference = pending.pop().ref
        if reference in references:
            continue
        references.add(reference)
        pending.extend(nodes[reference].children)
    return {_block_id(reference) for reference in references}


def _indexed_nodes(document: DoclingDocument) -> dict[str, DoclingNode]:
    nodes: dict[str, DoclingNode] = {}
    for node in chain(document.texts, document.tables, document.pictures, document.groups):
        reference = node.self_ref
        if reference in nodes:
            raise ValueError(f"Duplicate Docling node: {reference}")
        nodes[reference] = node
    return nodes


def _ordered_nodes(
    document: DoclingDocument,
    nodes: dict[str, DoclingNode],
) -> Iterator[DoclingNode]:
    pending = list(reversed(document.body.children))
    visited: set[str] = set()
    while pending:
        reference = pending.pop().ref
        if reference in visited:
            continue
        if reference not in nodes:
            raise ValueError(f"Missing Docling node: {reference}")
        visited.add(reference)
        node = nodes[reference]
        yield node
        children = [
            *node.children,
            *node.captions,
            *node.footnotes,
            *node.references,
        ]
        pending.extend(reversed(children))

    for reference, node in nodes.items():
        if reference not in visited:
            yield node


def _block_id(reference: str) -> str:
    return reference.removeprefix("#/").replace("/", "-")


def _parse_block(
    node: DoclingNode,
    document: DoclingDocument,
    nodes: dict[str, DoclingNode],
) -> document_models.DocumentBlock:
    locations = [_parse_location(provenance, document) for provenance in node.prov]
    label = node.label
    table = node.data if label == "table" else DoclingTable()
    captions = node.captions
    block = document_models.DocumentBlock(
        id=_block_id(node.self_ref),
        kind=BLOCK_KINDS.get(label, label),
        text=node.text,
        heading_level=node.level if node.level is not None else (1 if label == "title" else 0),
        page=locations[0].page if locations else None,
        region=locations[0].region if locations else None,
        locations=locations,
        label=label,
        caption="\n".join(nodes[caption.ref].text for caption in captions),
        caption_ids=[_block_id(caption.ref) for caption in captions],
        footnote_ids=[_block_id(footnote.ref) for footnote in node.footnotes],
        rows=table.num_rows,
        columns=table.num_cols,
        cells=[_parse_cell(cell) for cell in table.table_cells],
        method="docling",
    )
    block.issues = _block_issues(block)
    return block


def _parse_location(
    provenance: DoclingProvenance, document: DoclingDocument
) -> document_models.DocumentLocation:
    page = provenance.page_no
    bounding_box = provenance.bbox
    if not bounding_box:
        return document_models.DocumentLocation(page=page, region=None)

    left, top = bounding_box.left, bounding_box.top
    right, bottom = bounding_box.right, bounding_box.bottom
    origin = bounding_box.coord_origin
    if origin == "BOTTOMLEFT":
        height = document.pages[str(page)].height
        top, bottom = height - top, height - bottom
    elif origin != "TOPLEFT":
        raise ValueError(f"Unknown Docling coordinate origin: {origin}")
    if right < left or bottom < top:
        raise ValueError("Invalid Docling region dimensions")
    return document_models.DocumentLocation(page=page, region=(left, top, right, bottom))


def _parse_cell(cell: DoclingCell) -> document_models.TableCell:
    return document_models.TableCell(
        row=cell.start_row_offset_idx,
        column=cell.start_col_offset_idx,
        row_span=cell.end_row_offset_idx - cell.start_row_offset_idx,
        column_span=cell.end_col_offset_idx - cell.start_col_offset_idx,
        text=cell.text,
        header=cell.column_header,
        row_header=cell.row_header or cell.row_section,
    )


def _block_issues(block: document_models.DocumentBlock) -> list[str]:
    issues = []
    if not block.locations:
        issues.append("PDF location unavailable")
    if block.kind == "table" and len({location.page for location in block.locations}) > 1:
        issues.append("Multi-page content requires continuation review")
    if block.kind == "table":
        issues.extend(extraction_quality.table_issues(block))
    return issues


def page_sizes(document: DoclingDocument | Mapping[str, object]) -> dict[int, tuple[float, float]]:
    """Read original PDF page dimensions for region previews."""
    document = DoclingDocument.model_validate(document)
    if "pages" not in document.model_fields_set:
        raise ValueError("Docling document is missing its pages")
    return {int(number): (page.width, page.height) for number, page in document.pages.items()}
