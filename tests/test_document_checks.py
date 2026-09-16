from knowledge.document_processing.document_models import DocumentBlock, TableCell
from knowledge.document_processing.extraction_quality import compare_tables, table_issues
from knowledge.document_processing.marker_parser import marker_blocks, parse_table


def table(cells: list[TableCell], rows: int = 2, columns: int = 2) -> DocumentBlock:
    return DocumentBlock(id="table", kind="table", cells=cells, rows=rows, columns=columns)


def test_table_html_preserves_merged_headers_and_superscript_text():
    cells = parse_table(
        '<table><tr><th colspan="2">Year</th></tr>'
        '<tr><th scope="row">Group</th><td>42<sup>1</sup></td></tr></table>'
    )
    assert cells[0].column_span == 2
    assert cells[0].header
    assert cells[1].row_header
    assert cells[2].text == "421"
    assert table_issues(table(cells)) == []


def test_rowspan_reserves_column_on_following_rows():
    cells = parse_table('<tr><td rowspan="2">Group</td><td>1</td></tr><tr><td>2</td></tr>')
    assert [(cell.row, cell.column) for cell in cells] == [(0, 0), (0, 1), (1, 1)]
    assert table_issues(table(cells)) == []


def test_overlap_and_missing_cells_remain_visible():
    cells = [
        TableCell(row=0, column=0, column_span=2, text="A"),
        TableCell(row=0, column=1, text="B"),
    ]
    issues = table_issues(table(cells))
    assert any("Overlapping" in issue for issue in issues)
    assert any("uncovered" in issue for issue in issues)


def test_comparison_does_not_normalize_numbers_or_header_roles():
    original = table([TableCell(row=0, column=0, text="100  %", header=True)], 1, 1)
    reading = table([TableCell(row=0, column=0, text="100\n%", header=True)], 1, 1)
    assert compare_tables(original, reading) == []
    reading.cells[0].header = False
    assert compare_tables(original, reading)
    reading.cells[0].header = True
    reading.cells[0].text = "1001 %"
    assert compare_tables(original, reading)
    assert original.cells[0].text == "100  %"


def test_marker_restores_original_page_and_pdf_coordinates():
    output = {
        "block_type": "Document",
        "children": [
            {
                "block_type": "Page",
                "polygon": [[0, 0], [1200, 0], [1200, 1600], [0, 1600]],
                "children": [
                    {
                        "id": "/page/0/Table/1",
                        "block_type": "Table",
                        "children": None,
                        "polygon": [[100, 200], [1100, 200], [1100, 600], [100, 600]],
                        "html": "<table><tr><td>42</td></tr></table>",
                    }
                ],
            }
        ],
    }
    block = marker_blocks(output, 21, (600, 800))[0]
    assert block.page == 21
    assert block.region == (50, 100, 550, 300)
    assert block.cells[0].text == "42"
    assert block.method == "marker-raster"


def test_reconciliation_keeps_primary_identity_and_footnotes_with_changed_marker_cells():
    from knowledge.document_processing.extraction_quality import reconcile_blocks

    primary = table([TableCell(row=0, column=0, text="41")], 1, 1)
    primary.page = 21
    primary.region = (10, 10, 200, 200)
    primary.footnote_ids = ["footnote-1"]
    candidate = primary.model_copy(deep=True)
    candidate.id = "marker-table"
    candidate.cells[0].text = "42"
    footnote = DocumentBlock(id="footnote-1", kind="footnote", text="Source note", page=21)
    result = reconcile_blocks([primary, footnote], [candidate])
    assert result[0].id == primary.id
    assert result[0].cells[0].text == "42"
    assert result[0].footnote_ids == ["footnote-1"]
    assert any("disagree" in issue for issue in result[0].issues)
    assert result[1] == footnote
    assert primary.cells[0].text == "41"


def test_scan_reading_retains_footnotes_missing_from_marker():
    from knowledge.document_processing.extraction_quality import reconcile_blocks

    original = DocumentBlock(id="original", kind="text", text="bad OCR", page=3)
    footnote = DocumentBlock(id="footnote", kind="footnote", text="18: Original note", page=3)
    reading = DocumentBlock(id="marker", kind="text", text="Raster reading", page=3)
    result = reconcile_blocks([original, footnote], [reading], scan_pages={3})
    assert [block.id for block in result] == ["marker", "footnote"]
    assert all(block.issues for block in result)


def test_table_runs_preserve_superscripts_subscripts_and_inline_segments():
    cells = parse_table("<tr><td>42<sup>1<i>a</i></sup> H<sub>2</sub>O</td></tr>")
    assert [(run.text, run.script) for run in cells[0].runs] == [
        ("42", "normal"),
        ("1a", "sup"),
        (" H", "normal"),
        ("2", "sub"),
        ("O", "normal"),
    ]
    assert cells[0].text == "421a H2O"
    flattened = cells[0].model_copy(update={"runs": []})
    assert compare_tables(table(cells, 1, 1), table([flattened], 1, 1))


def test_unmatched_marker_table_is_visible_with_review_warning():
    from knowledge.document_processing.extraction_quality import reconcile_blocks

    paragraph = DocumentBlock(id="paragraph", kind="text", text="Body", page=1)
    candidate = table([TableCell(row=0, column=0, text="42")], 1, 1)
    candidate.page = 1
    candidate.region = (10, 10, 100, 100)
    selected = reconcile_blocks([paragraph], [candidate])
    assert len(selected) == 2
    assert selected[-1].cells[0].text == "42"
    assert any("no unique Docling match" in issue for issue in selected[-1].issues)
