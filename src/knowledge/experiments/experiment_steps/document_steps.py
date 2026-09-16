"""Extract source text, segment blocks, and formulate grounded claims.

The operations share exact source offsets but remain independent of experiment
storage, production acceptance, Zotero, and database orchestration.
"""

from typing import cast

from knowledge.experiments import pipeline_specification
from knowledge.experiments.experiment_steps import step_contracts
from knowledge.knowledge_domain import knowledge_record_models
from knowledge.source_workflows import (
    article_claim_extraction,
    information_block_extraction,
    structured_paper_extraction,
)


def validate_segmentation_parameters(parameters: dict) -> None:
    """Validate segmentation mode and maximum block size."""
    mode = parameters.get("mode", "paragraphs")
    if not isinstance(mode, str) or mode not in {"paragraphs", "model"}:
        raise ValueError("Segmentation mode must be paragraphs or model")
    maximum = parameters.get("max_characters", 2000)
    if type(maximum) is not int or not 1 <= maximum <= 120000:
        raise ValueError("max_characters must be an integer between 1 and 120000")


def extract_text(
    execution: pipeline_specification.StepExecution,
) -> information_block_extraction.TextExtraction:
    """Extract exact PDF text and optional provider-neutral paper structure."""
    return structured_paper_extraction.extract_paper_document(
        execution.pdf,
        execution.recipe.parameters,
        execution.output_directory,
        cancelled=execution.cancelled,
        timeout_seconds=execution.recipe.model.timeout_seconds,
        configuration=execution.recipe.model,
        cache_directory=execution.pdf.parent / "reference-cache",
    )


def segment_blocks(
    execution: pipeline_specification.StepExecution,
) -> information_block_extraction.InformationBlocks:
    """Create verbatim paragraphs or source-validated model segments."""
    extraction = execution.inputs["extract_text"]
    parameters = execution.recipe.parameters
    maximum = cast(int, parameters.get("max_characters", 2000))
    if parameters.get("mode", "paragraphs") == "paragraphs":
        return information_block_extraction.segment_verbatim(extraction, maximum)
    return information_block_extraction.segment_information(
        extraction,
        execution.prompt_text,
        execution.output_directory,
        execution.recipe.model,
        execution.cancelled,
        maximum,
    )


def claim_source_pins(
    proposal: knowledge_record_models.ExtractedClaim,
    blocks: information_block_extraction.InformationBlocks,
    extraction: information_block_extraction.TextExtraction,
) -> step_contracts.GroundedClaim:
    """Resolve an exact claim quote only within validated block source spans."""
    information_block_extraction.validate_blocks(blocks, extraction)
    indexes: list[int] = []
    sources: list[information_block_extraction.SourceSpan] = []
    for index, block in enumerate(blocks.blocks, 1):
        for source in block.sources:
            offset = source.quote.find(proposal.quote)
            if source.page != proposal.page or offset < 0:
                continue
            if source.quote.find(proposal.quote, offset + 1) >= 0:
                raise ValueError("Claim quote is ambiguous within its source span")
            indexes.append(index)
            sources.append(
                source.model_copy(
                    update={
                        "start": source.start + offset,
                        "end": source.start + offset + len(proposal.quote),
                        "quote": proposal.quote,
                    }
                )
            )
    if not sources:
        raise ValueError("Claim quote must occur inside a supplied information block")
    return step_contracts.GroundedClaim(
        proposal=proposal, block_indexes=sorted(set(indexes)), sources=sources
    )


def formulate_claims_from_blocks(
    execution: pipeline_specification.StepExecution,
) -> step_contracts.ClaimFormulation:
    """Generate claims while preserving the pinned information-block evidence."""
    extraction = execution.inputs["extract_text"]
    blocks = execution.inputs["segment_blocks"]
    information_block_extraction.validate_blocks(blocks, extraction)

    def validate(article: article_claim_extraction.ArticleExtraction) -> None:
        for claim in article.claims:
            claim_source_pins(claim, blocks, extraction)

    extractions = article_claim_extraction.extract_document(
        list(extraction.pages),
        execution.output_directory,
        instructions=execution.prompt_text,
        configuration=execution.recipe.model,
        cancelled=execution.cancelled,
        blocks_packet=blocks.model_dump(mode="json"),
        validate=validate,
    )
    claims = [
        claim_source_pins(claim, blocks, extraction)
        for article in extractions
        for claim in article.claims
    ]
    return step_contracts.ClaimFormulation(extractions=extractions, claims=claims)
