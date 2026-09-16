"""Translate Docling JSON into ordered document blocks.

The parser retains locations, table structure, reading order, and quality issues
without importing the Docling runtime.
"""

from collections.abc import Iterator
from typing import Any

from knowledge.document_processing import document_models, extraction_quality

ITEM_COLLECTIONS = ("texts", "tables", "pictures", "groups")
SECTION_KINDS = {
    "abstract": "abstract",
    "zusammenfassung": "abstract",
    "references": "reference",
    "bibliography": "reference",
    "literaturverzeichnis": "reference",
}
BLOCK_KINDS = {
    "section_header": "heading",
    "title": "heading",
    "picture": "figure",
    "list_item": "text",
    "page_header": "furniture",
    "page_footer": "furniture",
}


def parse_document(document: dict[str, Any]) -> list[document_models.DocumentBlock]:
    """Preserve body order and recover attached or otherwise unlisted source content."""
    if document.get("schema_name") != "DoclingDocument":
        raise ValueError("Expected a DoclingDocument JSON export")

    nodes = _indexed_nodes(document)
    blocks = []
    for node in _ordered_nodes(document, nodes):
        if node.get("self_ref", "").startswith("#/groups/"):
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
    document: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
) -> set[str]:
    pending = list(document.get("body", {}).get("children", []))
    references: set[str] = set()
    while pending:
        reference = pending.pop()["$ref"]
        if reference in references:
            continue
        references.add(reference)
        pending.extend(nodes[reference].get("children", []))
    return {_block_id(reference) for reference in references}


def _indexed_nodes(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = {}
    for collection in ITEM_COLLECTIONS:
        for node in document.get(collection, []):
            reference = node["self_ref"]
            if reference in nodes:
                raise ValueError(f"Duplicate Docling node: {reference}")
            nodes[reference] = node
    return nodes


def _ordered_nodes(
    document: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    pending = list(reversed(document.get("body", {}).get("children", [])))
    visited: set[str] = set()
    while pending:
        reference = pending.pop()["$ref"]
        if reference in visited:
            continue
        if reference not in nodes:
            raise ValueError(f"Missing Docling node: {reference}")
        visited.add(reference)
        node = nodes[reference]
        yield node
        children = [
            *node.get("children", []),
            *node.get("captions", []),
            *node.get("footnotes", []),
            *node.get("references", []),
        ]
        pending.extend(reversed(children))

    for reference, node in nodes.items():
        if reference not in visited:
            yield node


def _block_id(reference: str) -> str:
    return reference.removeprefix("#/").replace("/", "-")


def _parse_block(
    node: dict[str, Any],
    document: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
) -> document_models.DocumentBlock:
    locations = [_parse_location(provenance, document) for provenance in node.get("prov", [])]
    label = node.get("label", "text")
    table = node.get("data", {}) if label == "table" else {}
    captions = node.get("captions", [])
    block = document_models.DocumentBlock(
        id=_block_id(node["self_ref"]),
        kind=BLOCK_KINDS.get(label, label),
        text=node.get("text", ""),
        heading_level=node.get("level", 1 if label == "title" else 0),
        page=locations[0].page if locations else None,
        region=locations[0].region if locations else None,
        locations=locations,
        label=label,
        caption="\n".join(nodes[caption["$ref"]].get("text", "") for caption in captions),
        caption_ids=[_block_id(caption["$ref"]) for caption in captions],
        footnote_ids=[_block_id(footnote["$ref"]) for footnote in node.get("footnotes", [])],
        rows=table.get("num_rows", 0),
        columns=table.get("num_cols", 0),
        cells=[_parse_cell(cell) for cell in table.get("table_cells", [])],
        method="docling",
    )
    block.issues = _block_issues(block)
    return block


def _parse_location(
    provenance: dict[str, Any], document: dict[str, Any]
) -> document_models.DocumentLocation:
    page = int(provenance["page_no"])
    bounding_box = provenance.get("bbox")
    if not bounding_box:
        return document_models.DocumentLocation(page=page, region=None)

    left, top = float(bounding_box["l"]), float(bounding_box["t"])
    right, bottom = float(bounding_box["r"]), float(bounding_box["b"])
    origin = bounding_box.get("coord_origin")
    if origin == "BOTTOMLEFT":
        height = float(document["pages"][str(page)]["size"]["height"])
        top, bottom = height - top, height - bottom
    elif origin != "TOPLEFT":
        raise ValueError(f"Unknown Docling coordinate origin: {origin}")
    if right < left or bottom < top:
        raise ValueError("Invalid Docling region dimensions")
    return document_models.DocumentLocation(page=page, region=(left, top, right, bottom))


def _parse_cell(cell: dict[str, Any]) -> document_models.TableCell:
    return document_models.TableCell(
        row=cell["start_row_offset_idx"],
        column=cell["start_col_offset_idx"],
        row_span=cell["end_row_offset_idx"] - cell["start_row_offset_idx"],
        column_span=cell["end_col_offset_idx"] - cell["start_col_offset_idx"],
        text=cell.get("text", ""),
        header=cell.get("column_header", False),
        row_header=cell.get("row_header", False) or cell.get("row_section", False),
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


def page_sizes(document: dict[str, Any]) -> dict[int, tuple[float, float]]:
    """Read original PDF page dimensions for region previews."""
    return {
        int(number): (float(page["size"]["width"]), float(page["size"]["height"]))
        for number, page in document["pages"].items()
    }
