from copy import deepcopy

import pytest

from knowledge.document_parser import page_sizes, parse_document


def text_node(index, text, label="text"):
    return {
        "self_ref": f"#/texts/{index}",
        "label": label,
        "text": text,
        "prov": [
            {
                "page_no": 1,
                "bbox": {
                    "l": 10,
                    "t": 700,
                    "r": 200,
                    "b": 650,
                    "coord_origin": "BOTTOMLEFT",
                },
            }
        ],
    }


@pytest.fixture
def document():
    heading = text_node(0, "Results", "section_header")
    heading["level"] = 2
    return {
        "schema_name": "DoclingDocument",
        "pages": {"1": {"size": {"width": 600, "height": 800}}},
        "body": {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/tables/0"}]},
        "texts": [
            heading,
            text_node(1, "Table 2: Measured values", "caption"),
            text_node(2, "1 Includes all participants.", "footnote"),
            text_node(3, "18 See methods.", "footnote"),
        ],
        "tables": [
            {
                "self_ref": "#/tables/0",
                "label": "table",
                "prov": heading["prov"],
                "captions": [{"$ref": "#/texts/1"}],
                "footnotes": [{"$ref": "#/texts/2"}],
                "data": {
                    "num_rows": 1,
                    "num_cols": 2,
                    "table_cells": [
                        {
                            "start_row_offset_idx": 0,
                            "end_row_offset_idx": 1,
                            "start_col_offset_idx": 0,
                            "end_col_offset_idx": 2,
                            "text": "2024 (%)",
                            "column_header": True,
                        }
                    ],
                },
            }
        ],
    }


def test_preserve_body_order_merged_headers_and_all_footnotes(document):
    blocks = parse_document(document)
    assert [block.id for block in blocks] == [
        "texts-0",
        "tables-0",
        "texts-1",
        "texts-2",
        "texts-3",
    ]
    assert blocks[0].heading_level == 2
    table = blocks[1]
    assert table.caption == "Table 2: Measured values"
    assert table.caption_ids == ["texts-1"]
    assert table.footnote_ids == ["texts-2"]
    assert table.cells[0].column_span == 2
    assert table.cells[0].header
    assert not table.issues
    assert blocks[-1].text == "18 See methods."


def test_convert_pdf_origin_without_changing_page_units(document):
    block = parse_document(document)[0]
    assert block.page == 1
    assert block.region == (10, 100, 200, 150)
    assert page_sizes(document) == {1: (600, 800)}


def test_unlocated_text_remains_explicitly_unlocated(document):
    document["texts"][0]["prov"] = []
    block = parse_document(document)[0]
    assert block.page is None
    assert block.region is None
    assert "PDF location unavailable" in block.issues


def test_overlapping_table_cells_are_visible_as_quality_problem(document):
    table = document["tables"][0]
    table["data"]["table_cells"].append(deepcopy(table["data"]["table_cells"][0]))
    assert "Overlapping cells at row 1, column 1" in parse_document(document)[1].issues


def test_preserve_multi_page_locations_and_require_continuation_review(document):
    table = document["tables"][0]
    document["pages"]["2"] = document["pages"]["1"]
    second_page = deepcopy(table["prov"][0])
    second_page["page_no"] = 2
    table["prov"] = [*table["prov"], second_page]
    block = parse_document(document)[1]
    assert [location.page for location in block.locations] == [1, 2]
    assert "Multi-page content requires continuation review" in block.issues


def test_reject_dangling_document_references(document):
    document["body"]["children"].append({"$ref": "#/texts/99"})
    with pytest.raises(ValueError, match="Missing Docling node"):
        parse_document(document)


def test_keep_figure_caption_and_original_region(document):
    document["pictures"] = [
        {
            "self_ref": "#/pictures/0",
            "label": "picture",
            "prov": document["texts"][0]["prov"],
            "captions": [{"$ref": "#/texts/1"}],
        }
    ]
    document["body"]["children"].append({"$ref": "#/pictures/0"})
    figure = next(block for block in parse_document(document) if block.kind == "figure")
    assert figure.caption_ids == ["texts-1"]
    assert figure.region == (10, 100, 200, 150)


@pytest.mark.parametrize("heading", ["Abstract", "Zusammenfassung", "ABSTRACT"])
def test_abstract_section_requires_explicit_heading_and_ends_at_next_heading(document, heading):
    document["texts"] = [
        text_node(0, heading, "section_header"),
        text_node(1, "Exact abstract."),
        text_node(2, "Introduction", "section_header"),
        text_node(3, "Main text."),
    ]
    document["tables"] = []
    document["body"]["children"] = [{"$ref": node["self_ref"]} for node in document["texts"]]
    blocks = parse_document(document)
    assert [block.kind for block in blocks] == ["heading", "abstract", "heading", "text"]
    assert blocks[1].text == "Exact abstract."


@pytest.mark.parametrize("heading", ["References", "Bibliography", "Literaturverzeichnis"])
def test_reference_section_keeps_list_order_and_footnotes_distinct(document, heading):
    document["texts"] = [
        text_node(0, heading, "section_header"),
        text_node(1, "1. First reference.", "list_item"),
        text_node(2, "2. Second reference.", "list_item"),
        text_node(3, "Footnote.", "footnote"),
        text_node(4, "Unlinked content."),
    ]
    document["tables"] = []
    document["groups"] = [
        {
            "self_ref": "#/groups/0",
            "label": "list",
            "children": [{"$ref": "#/texts/1"}, {"$ref": "#/texts/2"}],
        }
    ]
    document["body"]["children"] = [
        {"$ref": "#/texts/0"},
        {"$ref": "#/groups/0"},
        {"$ref": "#/texts/3"},
    ]
    blocks = parse_document(document)
    assert [block.kind for block in blocks] == [
        "heading",
        "reference",
        "reference",
        "footnote",
        "text",
    ]
    assert [block.text for block in blocks[1:3]] == ["1. First reference.", "2. Second reference."]


def test_no_section_semantics_inferred_from_prose_or_approximate_heading(document):
    document["texts"][0]["text"] = "References and further reading"
    document["texts"][1]["label"] = "text"
    document["texts"][1]["text"] = "Abstract: This remains source prose."
    document["body"]["children"] = [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}]
    assert parse_document(document)[1].kind == "text"
