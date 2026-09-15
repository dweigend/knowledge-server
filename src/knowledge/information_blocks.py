"""Extract pinned PDF text and form inspectable, source-grounded information blocks."""

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator

from knowledge.contracts import Contract
from knowledge.generation import ModelConfiguration, generate
from knowledge.ingestion import extract_pdf_pages

EXTRACTION_METHOD = "pdftotext reading-order; v3"
MAX_INPUT_CHARACTERS = 120000
MAX_BLOCKS = 500


def text_revision(pdf_sha256: str, pages: tuple[str, ...], method: str) -> str:
    """Hash the original PDF identity and exact extracted text with its method."""
    encoded = json.dumps([pdf_sha256, pages, method], ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


class TextExtraction(Contract):
    """Pin original page text without requiring a Zotero registration."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=False)

    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    pages: tuple[str, ...] = Field(min_length=1)
    method: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        """Reject text or method changes that retain an earlier revision identity."""
        if self.revision != text_revision(self.pdf_sha256, self.pages, self.method):
            raise ValueError("Extraction revision does not match its PDF, text and method")
        return self


class SourceSpan(Contract):
    """Locate verbatim text using zero-based, end-exclusive Python character offsets."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=False)

    extraction_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)


class InformationBlock(Contract):
    """Separate bullet wording from the exact source spans supporting one block."""

    bullets: list[str] = Field(min_length=1, max_length=30)
    sources: list[SourceSpan] = Field(min_length=1, max_length=50)
    wording: Literal["paraphrase", "verbatim"]


class InformationBlocks(Contract):
    """Return only individual blocks, each with bullets and source spans."""

    blocks: list[InformationBlock] = Field(max_length=MAX_BLOCKS)


def extract_text(pdf: Path) -> TextExtraction:
    """Use the production PDF extraction and reject input changes during extraction."""
    before = hashlib.sha256(pdf.read_bytes()).hexdigest()
    pages = tuple(extract_pdf_pages(pdf))
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != before:
        raise ValueError("PDF changed during extraction")
    return TextExtraction(
        pdf_sha256=before,
        revision=text_revision(before, pages, EXTRACTION_METHOD),
        pages=pages,
        method=EXTRACTION_METHOD,
    )


def validate_span(span: SourceSpan, extraction: TextExtraction) -> None:
    """Require an exact quote at the declared offsets of the pinned extraction."""
    if span.extraction_revision != extraction.revision:
        raise ValueError("Source span cites a different extraction revision")
    if span.page > len(extraction.pages):
        raise ValueError("Source span cites a missing original PDF page")
    page = extraction.pages[span.page - 1]
    if span.end <= span.start or span.end > len(page):
        raise ValueError("Source span offsets are outside their original page")
    if page[span.start : span.end] != span.quote:
        raise ValueError("Source span quote does not match its exact page offsets")


def validate_blocks(blocks: InformationBlocks, extraction: TextExtraction) -> None:
    """Check every source pin and keep verbatim bullets distinct from paraphrases."""
    for block in blocks.blocks:
        for span in block.sources:
            validate_span(span, extraction)
        if any(not bullet.strip() for bullet in block.bullets):
            raise ValueError("Information block bullets must not be empty")
        if block.wording == "verbatim" and any(
            not any(bullet in span.quote for span in block.sources) for bullet in block.bullets
        ):
            raise ValueError("Verbatim bullets must appear unchanged in their source spans")


def segment_verbatim(extraction: TextExtraction, max_characters: int = 2000) -> InformationBlocks:
    """Group bounded paragraphs verbatim without claiming semantic segmentation."""
    if not 1 <= max_characters <= MAX_INPUT_CHARACTERS:
        raise ValueError("Paragraph character budget must be between 1 and 120000")
    blocks = []
    for number, page in enumerate(extraction.pages, 1):
        for match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", page, re.DOTALL):
            start, end = match.span()
            while start < end:
                stop = min(start + max_characters, end)
                quote = page[start:stop]
                if quote.strip():
                    span = SourceSpan(
                        extraction_revision=extraction.revision,
                        page=number,
                        start=start,
                        end=stop,
                        quote=quote,
                    )
                    blocks.append(
                        InformationBlock(bullets=[quote], sources=[span], wording="verbatim")
                    )
                if len(blocks) > MAX_BLOCKS:
                    raise ValueError("Segmentation exceeds 500 blocks; increase the budget")
                start = stop
    result = InformationBlocks(blocks=blocks)
    validate_blocks(result, extraction)
    return result


def segment_information(
    extraction: TextExtraction,
    instructions: str,
    output_directory: Path,
    configuration: ModelConfiguration | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> InformationBlocks:
    """Generate bounded information blocks through the shared validated model adapter."""
    if sum(map(len, extraction.pages)) > MAX_INPUT_CHARACTERS:
        raise ValueError("Information segmentation exceeds the 120000-character input budget")
    packet = extraction.model_dump_json()
    return generate(
        instructions,
        packet,
        InformationBlocks,
        output_directory,
        lambda result: validate_blocks(result, extraction),
        configuration=configuration,
        cancelled=cancelled,
    )
