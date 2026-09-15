"""Resolve historical quotations and prepare temporary cover-free PDF derivatives."""

import re
import subprocess
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def normalized_with_offsets(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Normalize spacing and typographic ligatures while retaining exact offsets."""
    ligatures = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
    characters = []
    offsets = []
    for match in re.finditer(r"\s+|.", text, flags=re.DOTALL):
        token = match.group()
        normalized = " " if token.isspace() else ligatures.get(token, token)
        characters.append(normalized)
        offsets.extend([(match.start(), match.end())] * len(normalized))
    return "".join(characters), offsets


def locate_quote(page: str, proposed_quote: str) -> str:
    """Restore PDF typography only; reject changed wording or ambiguous matches."""
    normalized_page, offsets = normalized_with_offsets(page)
    normalized_quote, _ = normalized_with_offsets(proposed_quote)
    if not normalized_quote.strip():
        raise ValueError("Empty quote")
    matches = list(re.finditer(re.escape(normalized_quote), normalized_page))
    if len(matches) != 1:
        raise ValueError("Quote does not have one exact wording match on its source page")
    match = matches[0]
    return page[offsets[match.start()][0] : offsets[match.end() - 1][1]]


def locate_passage(pages: list[str], page: int, quote: str) -> tuple[int, str]:
    """Resolve a unique verbatim passage when a model confuses PDF and printed pages."""
    supplied_page = pages[page - 1] if 1 <= page <= len(pages) else None
    exact_quote = quote_on_page(supplied_page, quote)
    if exact_quote is not None:
        return page, exact_quote

    matches = []
    for index, content in enumerate(pages, 1):
        exact_quote = quote_on_page(content, quote)
        if exact_quote is not None:
            matches.append((index, exact_quote))
    if len(matches) != 1:
        raise ValueError("No unique exact passage in the supplied source")
    return matches[0]


def extract_pdf_pages(pdf_path: Path) -> list[str]:
    """Extract reading-order page text and reject PDFs needing manual preparation."""
    extracted = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    pages = extracted.split("\f")
    if not pages[-1].strip():
        pages.pop()
    if len(pages) < 3 or sum(map(len, pages[1:])) < 2000:
        raise ValueError("PDF needs manual extraction QA or OCR")
    return pages


def remove_curator_cover(archived: Path, clean: Path) -> None:
    """Create a read-only derivative without the first page, retaining existing output."""
    if clean.exists():
        return
    reader = PdfReader(archived)
    writer = PdfWriter()
    writer.append(reader, pages=(1, len(reader.pages)), import_outline=False)
    temporary = clean.with_suffix(".tmp.pdf")
    writer.write(temporary)
    temporary.replace(clean)
    clean.chmod(0o400)


def quote_on_page(page: str | None, quote: str) -> str | None:
    """A missing or nonmatching page permits searching the remaining supplied pages."""
    if page is None:
        return None
    try:
        return locate_quote(page, quote)
    except ValueError:
        return None
