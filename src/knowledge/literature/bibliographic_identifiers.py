"""Validate supplied ISBN evidence without inferring missing bibliographic facts."""

import re

from knowledge.literature.literature_models import LiteratureMetadata
from knowledge.literature.structured_paper_models import PaperMetadata, PaperReference

ISBN_LABEL = re.compile(r"\bISBN(?:-1[03])?\s*:?\s*", re.IGNORECASE)
ISBN_13 = re.compile(r"(?<!\d)97[89](?:[\s-]*\d){10}(?!\d)")
ISBN_10 = re.compile(r"\d(?:[\s-]*\d){8}[\s-]*[\dXx](?!\d)")


def normalize_isbn(identifier: str | None) -> str | None:
    """Validate an ISBN checksum and return its canonical ISBN-13 representation."""
    cleaned = ISBN_LABEL.sub("", (identifier or "").strip(), count=1)
    cleaned = re.sub(r"[\s-]", "", cleaned).upper()
    if re.fullmatch(r"\d{9}[\dX]", cleaned):
        digits = [10 if digit == "X" else int(digit) for digit in cleaned]
        if sum((10 - index) * digit for index, digit in enumerate(digits)) % 11:
            return None
        prefix = "978" + cleaned[:9]
        return prefix + _check_digit(prefix)
    if re.fullmatch(r"97[89]\d{10}", cleaned) and cleaned[-1] == _check_digit(cleaned[:12]):
        return cleaned
    return None


def extracted_isbn(reference: PaperMetadata) -> str | None:
    """Return one unambiguous valid ISBN from supplied metadata or literal citation text."""
    supplied = reference.isbn if isinstance(reference, LiteratureMetadata) else []
    identifiers = {normalized for entry in supplied if (normalized := normalize_isbn(entry))}
    raw = reference.raw if isinstance(reference, PaperReference) else ""
    for match in ISBN_13.finditer(raw or ""):
        if normalized := normalize_isbn(match.group()):
            identifiers.add(normalized)
    for label in ISBN_LABEL.finditer(raw or ""):
        tail = (raw or "")[label.end() :]
        match = ISBN_13.match(tail) or ISBN_10.match(tail)
        if match and (normalized := normalize_isbn(match.group())):
            identifiers.add(normalized)
    return next(iter(identifiers)) if len(identifiers) == 1 else None


def _check_digit(prefix: str) -> str:
    weighted = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(prefix))
    return str((-weighted) % 10)
