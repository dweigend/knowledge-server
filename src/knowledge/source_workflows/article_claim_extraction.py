"""Extract bounded claim proposals from source documents.

This proposal boundary chunks page text, invokes structured generation, and
validates exact quotations without importing source registration or persistence.
"""

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import Field

from knowledge.document_processing import pdf_text_extraction
from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.model_integration import prompt_registry, structured_generation
from knowledge.runtime_support import workflow_event_log

PAGE_BUDGET = 65000


class ArticleExtraction(models.Contract):
    """Extract a bounded contribution without requiring a new note per document."""

    bibliography: models.Bibliography
    claims: list[models.ExtractedClaim] = Field(max_length=1)
    study_group: models.Text
    overlap: models.Text
    warnings: list[str]


def page_chunks(pages: list[str]) -> list[dict[int, str]]:
    """Partition every evidence page without losing original PDF numbering."""
    chunks: list[dict[int, str]] = []
    current: dict[int, str] = {}
    characters = 0
    for number, text in enumerate(pages, 1):
        if text == "[Curator cover excluded from evidence]":
            continue
        if len(text) > PAGE_BUDGET:
            raise ValueError(f"PDF page {number} exceeds extraction budget")
        if current and characters + len(text) > PAGE_BUDGET:
            chunks.append(current)
            current, characters = {}, 0
        current[number] = text
        characters += len(text)
    if current:
        chunks.append(current)
    return chunks


def validate_extraction(
    extraction: ArticleExtraction, pages: list[str], supplied: dict[int, str]
) -> None:
    """Restore exact quote typography and reject quotations outside the supplied pages."""
    for claim in extraction.claims:
        claimed_page = claim.page
        claim.page, claim.quote = pdf_text_extraction.locate_passage(
            pages, claimed_page, claim.quote
        )
        if claim.page not in supplied:
            raise ValueError("Quote is outside the supplied chunk")
        if claimed_page != claim.page:
            extraction.warnings.append(f"Corrected PDF page {claimed_page} to {claim.page}")


def validate_import_proposal(
    proposal: ArticleExtraction,
    pages: list[str],
    supplied: dict[int, str],
    validate: Callable[[ArticleExtraction], None] | None,
) -> None:
    """Apply exact import citation checks and optional additional source-boundary checks."""
    validate_extraction(proposal, pages, supplied)
    if validate is not None:
        validate(proposal)


def extract_document(
    pages: list[str],
    run_directory: Path,
    *,
    instructions: str | None = None,
    configuration: structured_generation.ModelConfiguration | None = None,
    cancelled: Callable[[], bool] | None = None,
    blocks_packet: dict | None = None,
    validate: Callable[[ArticleExtraction], None] | None = None,
) -> list[ArticleExtraction]:
    """Extract one inspectable contribution per complete page chunk."""
    if instructions is None:
        instructions, default_configuration = prompt_registry.operation_configuration(
            "formulate_claims"
        )
        configuration = configuration or default_configuration

    proposals: list[ArticleExtraction] = []
    for chunk in page_chunks(pages):
        packet = json.dumps(
            {
                "pages": chunk,
                "known_bibliography": proposals[0].bibliography.model_dump(mode="json")
                if proposals
                else None,
                **({"information_blocks": blocks_packet} if blocks_packet is not None else {}),
            },
            ensure_ascii=False,
        )
        proposal = structured_generation.generate(
            instructions,
            packet,
            ArticleExtraction,
            run_directory / "proposals",
            lambda result, supplied=chunk: validate_import_proposal(
                result, pages, supplied, validate
            ),
            configuration=configuration,
            cancelled=cancelled,
        )
        workflow_event_log.record_event(
            run_directory,
            "extraction",
            pages=list(chunk),
            claims=len(proposal.claims),
            warnings=proposal.warnings,
        )
        proposals.append(proposal)
    return proposals


def merge_extracted_metadata(
    extractions: list[ArticleExtraction], run_directory: Path
) -> models.Bibliography:
    """Fill metadata gaps from later chunks and log conflicts without overwriting known fields."""
    merged = {}
    for field in ("title", "authors", "year", "doi", "url"):
        values = distinct_metadata_values(extractions, field)
        merged[field] = values[0] if values else ([] if field == "authors" else "")
        if len(values) > 1:
            workflow_event_log.record_event(
                run_directory,
                "metadata_conflict",
                field=field,
                retained=values[0],
                distinct_values=values,
            )
    return models.Bibliography.model_validate(merged)


def distinct_metadata_values(extractions: list[ArticleExtraction], field: str) -> list:
    """Keep distinct nonempty values in source-chunk order."""
    values = []
    for extraction in extractions:
        value = getattr(extraction.bibliography, field)
        if value and value not in values:
            values.append(value)
    return values
