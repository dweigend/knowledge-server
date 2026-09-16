"""Extract pinned PDF text and derive inspectable information blocks.

Every proposed block must resolve to exact source spans and remain within
configured segmentation budgets.
"""

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator

from knowledge.document_processing import pdf_text_extraction
from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.literature import literature_models, structured_paper_models
from knowledge.model_integration import structured_generation
from knowledge.runtime_support import workflow_event_log

EXTRACTION_METHOD = "pdftotext reading-order; v3"
MAX_INPUT_CHARACTERS = 120000
MAX_BLOCKS = 500


def text_revision(pdf_sha256: str, pages: tuple[str, ...], method: str) -> str:
    """Hash the original PDF identity and exact extracted text with its method."""
    encoded = json.dumps([pdf_sha256, pages, method], ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


class TextExtraction(models.Contract):
    """Pin original page text without requiring a Zotero registration."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=False)

    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    pages: tuple[str, ...] = Field(min_length=1)
    method: str = Field(min_length=1)
    paper: structured_paper_models.PaperDocument | None = None
    literature: list[literature_models.LiteratureRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        """Reject text or method changes that retain an earlier revision identity."""
        if self.revision != text_revision(self.pdf_sha256, self.pages, self.method):
            raise ValueError("Extraction revision does not match its PDF, text and method")
        return self


class SourceSpan(models.Contract):
    """Locate verbatim text using zero-based, end-exclusive Python character offsets."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=False)

    extraction_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)


class InformationBlock(models.Contract):
    """Separate bullet wording from the exact source spans supporting one block."""

    bullets: list[str] = Field(min_length=1, max_length=30)
    sources: list[SourceSpan] = Field(min_length=1, max_length=50)
    wording: Literal["paraphrase", "verbatim"]


class InformationBlocks(models.Contract):
    """Return only individual blocks, each with bullets and source spans."""

    blocks: list[InformationBlock] = Field(max_length=MAX_BLOCKS)


class QuoteReference(models.Contract):
    """Select an original page and exact wording; the resolver supplies offsets and revision."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=False)

    page: int = Field(ge=1)
    quote: str = Field(min_length=1)


class BlockProposal(models.Contract):
    """Propose block wording and quotation selections without guessing character positions."""

    bullets: list[str] = Field(min_length=1, max_length=30)
    sources: list[QuoteReference] = Field(min_length=1, max_length=50)
    wording: Literal["paraphrase", "verbatim"]


class BlockSegmentation(models.Contract):
    """Select source-grounded blocks for deterministic resolution into exact public spans."""

    blocks: list[BlockProposal] = Field(max_length=MAX_BLOCKS)


def resolve_source_quote(reference: QuoteReference, extraction: TextExtraction) -> SourceSpan:
    """Locate a unique, unchanged quote on its declared original PDF page."""
    if reference.page > len(extraction.pages):
        raise ValueError("Source quote cites a missing original PDF page")
    page = extraction.pages[reference.page - 1]
    quote = reference.quote
    start = page.find(quote)
    if not quote.strip() or start < 0 or page.find(quote, start + 1) >= 0:
        raise ValueError("Quote must have one exact wording match on its declared source page")
    return SourceSpan(
        extraction_revision=extraction.revision,
        page=reference.page,
        start=start,
        end=start + len(quote),
        quote=quote,
    )


def resolve_segmentation(
    proposal: BlockSegmentation, extraction: TextExtraction, max_characters: int | None = None
) -> InformationBlocks:
    """Produce exact source spans while preserving model paraphrases as separate wording."""
    blocks = InformationBlocks(
        blocks=[
            InformationBlock(
                bullets=block.bullets,
                sources=[
                    resolve_source_quote(reference, extraction) for reference in block.sources
                ],
                wording=block.wording,
            )
            for block in proposal.blocks
        ]
    )
    validate_segment_budget(blocks, extraction, max_characters)
    return blocks


def extract_text(
    pdf: Path,
    *,
    cancelled: Callable[[], bool] | None = None,
    timeout_seconds: float = 120,
) -> TextExtraction:
    """Use the production PDF extraction and reject input changes during extraction."""
    before = hashlib.sha256(pdf.read_bytes()).hexdigest()
    pages = tuple(
        pdf_text_extraction.extract_pdf_pages(
            pdf, cancelled=cancelled, timeout_seconds=timeout_seconds
        )
        if cancelled is not None or timeout_seconds != 120
        else pdf_text_extraction.extract_pdf_pages(pdf)
    )
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
    configuration: structured_generation.ModelConfiguration | None = None,
    cancelled: Callable[[], bool] | None = None,
    max_characters: int | None = None,
) -> InformationBlocks:
    """Generate bounded information blocks through the shared validated model adapter."""
    if sum(map(len, extraction.pages)) > MAX_INPUT_CHARACTERS:
        raise ValueError("Information segmentation exceeds the 120000-character input budget")
    if max_characters is not None and not 1 <= max_characters <= MAX_INPUT_CHARACTERS:
        raise ValueError("Block source character budget must be between 1 and 120000")
    packet = json.dumps(
        {
            "extraction": extraction.model_dump(mode="json"),
            "max_source_characters_per_block": max_characters,
        },
        ensure_ascii=False,
    )

    def validate(proposal: BlockSegmentation) -> None:
        resolve_segmentation(proposal, extraction, max_characters)

    proposal = structured_generation.generate(
        instructions,
        packet,
        BlockSegmentation,
        output_directory,
        validate,
        configuration=configuration,
        cancelled=cancelled,
    )
    result = resolve_segmentation(proposal, extraction, max_characters)
    workflow_event_log.record_event(
        output_directory,
        "source_spans_resolved",
        extraction_revision=extraction.revision,
        sources=[span.model_dump(mode="json") for block in result.blocks for span in block.sources],
    )
    return result


def validate_segment_budget(
    blocks: InformationBlocks, extraction: TextExtraction, max_characters: int | None
) -> None:
    """Check exact provenance and the explicitly requested total source text per block."""
    validate_blocks(blocks, extraction)
    if max_characters is not None and any(
        sum(len(source.quote) for source in block.sources) > max_characters
        for block in blocks.blocks
    ):
        raise ValueError("Information block exceeds max_source_characters_per_block")
