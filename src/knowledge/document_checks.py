"""Check extracted table structure and expose disagreements without repairing sources."""

from knowledge.document_contracts import DocumentBlock, TableCell


def _positions(cell: TableCell) -> set[tuple[int, int]]:
    return {
        (row, column)
        for row in range(cell.row, cell.row + cell.row_span)
        for column in range(cell.column, cell.column + cell.column_span)
    }


def table_issues(table: DocumentBlock) -> list[str]:
    """Find missing, overlapping or out-of-bounds table cells deterministically."""
    if not table.cells or table.rows < 1 or table.columns < 1:
        return ["Table has no usable cell grid"]
    occupied: set[tuple[int, int]] = set()
    issues: list[str] = []
    for cell in table.cells:
        positions = _positions(cell)
        if occupied.intersection(positions):
            issues.append(f"Overlapping cells at row {cell.row + 1}, column {cell.column + 1}")
        if cell.row + cell.row_span > table.rows or cell.column + cell.column_span > table.columns:
            issues.append(f"Cell outside table at row {cell.row + 1}, column {cell.column + 1}")
        occupied.update(positions)
    expected = {(row, column) for row in range(table.rows) for column in range(table.columns)}
    if expected - occupied:
        issues.append(f"Table has {len(expected - occupied)} uncovered cell positions")
    return issues


def _signature(cell: TableCell) -> tuple:
    return (
        cell.row_span,
        cell.column_span,
        cell.header,
        cell.row_header,
        " ".join(cell.text.split()),
        tuple(
            (run.script, " ".join(run.text.split())) for run in cell.runs if run.script != "normal"
        ),
    )


def compare_tables(primary: DocumentBlock, second_reading: DocumentBlock) -> list[str]:
    """Compare aligned cells and header roles, normalizing only whitespace."""
    issues = [*table_issues(primary), *table_issues(second_reading)]
    if (primary.rows, primary.columns) != (second_reading.rows, second_reading.columns):
        issues.append("Docling and Marker disagree on table dimensions")
    primary_cells = {(cell.row, cell.column): _signature(cell) for cell in primary.cells}
    reading_cells = {(cell.row, cell.column): _signature(cell) for cell in second_reading.cells}
    for row, column in sorted(primary_cells.keys() | reading_cells.keys()):
        if primary_cells.get((row, column)) != reading_cells.get((row, column)):
            issues.append(f"Docling and Marker disagree at row {row + 1}, column {column + 1}")
    return list(dict.fromkeys(issues))


def _overlaps(primary: DocumentBlock, candidate: DocumentBlock) -> bool:
    if primary.page != candidate.page or primary.region is None or candidate.region is None:
        return False
    left, top, right, bottom = primary.region
    other_left, other_top, other_right, other_bottom = candidate.region
    intersection = max(0, min(right, other_right) - max(left, other_left)) * max(
        0, min(bottom, other_bottom) - max(top, other_top)
    )
    smaller_area = min(
        (right - left) * (bottom - top), (other_right - other_left) * (other_bottom - other_top)
    )
    return smaller_area > 0 and intersection / smaller_area > 0.5


def _select_table(
    primary: DocumentBlock, candidates: list[DocumentBlock], originals: list[DocumentBlock]
) -> DocumentBlock:
    matches = [candidate for candidate in candidates if _overlaps(primary, candidate)]
    if len(matches) != 1:
        return primary.model_copy(
            update={
                "issues": [
                    *primary.issues,
                    "Marker table could not be matched unambiguously; review required",
                ]
            }
        )
    candidate = matches[0]
    if sum(_overlaps(original, candidate) for original in originals) != 1:
        return primary.model_copy(
            update={
                "issues": [
                    *primary.issues,
                    "Marker table overlaps multiple Docling tables; review required",
                ]
            }
        )
    return primary.model_copy(
        update={
            "cells": candidate.cells,
            "rows": candidate.rows,
            "columns": candidate.columns,
            "text": candidate.text,
            "method": "marker-raster",
            "issues": list(
                dict.fromkeys(
                    [*primary.issues, *candidate.issues, *compare_tables(primary, candidate)]
                )
            ),
        }
    )


def _scan_reading(
    primary: list[DocumentBlock], reading: list[DocumentBlock]
) -> list[DocumentBlock]:
    warning = "No usable PDF text layer; Marker raster reading requires review"
    selected = [block.model_copy(update={"issues": [*block.issues, warning]}) for block in reading]
    visible_text = {" ".join(block.text.split()) for block in reading}
    missing_notes = [
        block
        for block in primary
        if block.kind == "footnote" and " ".join(block.text.split()) not in visible_text
    ]
    selected.extend(
        block.model_copy(
            update={
                "issues": [
                    *block.issues,
                    "Docling footnote absent from Marker reading; retained for review",
                ]
            }
        )
        for block in missing_notes
    )
    return selected


def reconcile_blocks(
    primary: list[DocumentBlock],
    second_reading: list[DocumentBlock],
    scan_pages: set[int] | None = None,
) -> list[DocumentBlock]:
    """Select located Marker tables or explicit scan pages, preserving missing footnotes.

    Keep both candidates in snapshot audit provenance before calling this function.
    A missing PDF text layer is a review signal, not proof that a page is scanned.
    """
    selected = _reconcile_tables(primary, second_reading)
    for page in sorted(scan_pages or set()):
        reading = [block for block in second_reading if block.page == page]
        if not reading:
            continue
        original = [block for block in selected if block.page == page]
        position = next(
            (index for index, block in enumerate(selected) if block.page == page), len(selected)
        )
        selected = [block for block in selected if block.page != page]
        selected[position:position] = _scan_reading(original, reading)
    return selected


def _reconcile_tables(
    primary: list[DocumentBlock], second_reading: list[DocumentBlock]
) -> list[DocumentBlock]:
    checked_pages = {block.page for block in second_reading}
    candidates = [block for block in second_reading if block.kind == "table"]
    originals = [block for block in primary if block.kind == "table"]
    result = []
    for block in primary:
        if block.kind != "table" or block.page not in checked_pages:
            result.append(block)
            continue
        result.append(_select_table(block, candidates, originals))
    unmatched = [
        candidate
        for candidate in candidates
        if not _has_unique_match(candidate, originals, candidates)
    ]
    result.extend(
        candidate.model_copy(
            update={
                "issues": [
                    *candidate.issues,
                    "Additional Marker table has no unique Docling match; "
                    "verify location and duplication",
                ]
            }
        )
        for candidate in unmatched
    )
    return result


def _has_unique_match(
    candidate: DocumentBlock, originals: list[DocumentBlock], candidates: list[DocumentBlock]
) -> bool:
    matches = [original for original in originals if _overlaps(original, candidate)]
    return len(matches) == 1 and sum(_overlaps(matches[0], other) for other in candidates) == 1
