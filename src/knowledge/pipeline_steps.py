"""Expose shared, manually invoked domain operations to web and command-line callers."""

import difflib
from collections.abc import Callable
from pathlib import Path

from pydantic import Field

from knowledge.consolidation import ConsolidateNote, propose_note_revision
from knowledge.contracts import Contract, ExtractedClaim, Note, Record
from knowledge.generation import check_cancelled
from knowledge.import_workflow import ArticleExtraction, extract_document
from knowledge.information_blocks import (
    InformationBlocks,
    SourceSpan,
    TextExtraction,
    segment_information,
    segment_verbatim,
    validate_blocks,
)
from knowledge.knowledge_selection import (
    KnowledgeRetrieval,
    KnowledgeSelection,
    retrieve_knowledge,
    select_knowledge,
    validate_selection,
)
from knowledge.paper_extraction import extract_paper_document, validate_paper_parameters
from knowledge.prompt_registry import Recipe, get_revision
from knowledge.reconciliation import ClaimDecision, propose_matching
from knowledge.writing import WritingDraft, WritingPoints, draft_prose, prepare_writing_points

STEP_LABELS = {
    "extract_text": "Extract PDF text",
    "segment_blocks": "Segment information blocks",
    "formulate_claims": "Formulate claims",
    "find_knowledge": "Find existing knowledge",
    "select_entries": "Select relevant entries",
    "propose_changes": "Propose evidenced changes",
    "prepare_writing": "Prepare cited writing points",
    "draft_text": "Draft prose",
}
STEP_DEPENDENCIES = {
    "extract_text": (),
    "segment_blocks": ("extract_text",),
    "formulate_claims": ("extract_text", "segment_blocks"),
    "find_knowledge": ("formulate_claims",),
    "select_entries": ("formulate_claims", "find_knowledge"),
    "propose_changes": (
        "extract_text",
        "segment_blocks",
        "formulate_claims",
        "find_knowledge",
        "select_entries",
    ),
    "prepare_writing": ("extract_text", "segment_blocks", "formulate_claims", "propose_changes"),
    "draft_text": ("extract_text", "segment_blocks", "prepare_writing"),
}


class GroundedClaim(Contract):
    """Associate the unchanged import proposal with exact information-block provenance."""

    proposal: ExtractedClaim
    block_indexes: list[int] = Field(min_length=1)
    sources: list[SourceSpan] = Field(min_length=1)


class ClaimFormulation(Contract):
    """Retain import metadata and proposed claims without writing to a knowledge ledger."""

    extractions: list[ArticleExtraction]
    claims: list[GroundedClaim]


class ClaimChange(Contract):
    """Keep an evidence-relation proposal grounded in its original extracted passage."""

    claim: GroundedClaim
    decision: ClaimDecision


class NoteChange(Contract):
    """Present a validated existing-note proposal together with its exact text diff."""

    command: ConsolidateNote
    diff: str


class KnowledgeChanges(Contract):
    """Collect reviewable proposals without accepting or persisting domain records."""

    claims: list[ClaimChange]
    notes: list[NoteChange]
    warnings: list[str]


OUTPUT_CONTRACTS: dict[str, type[Contract]] = {
    "extract_text": TextExtraction,
    "segment_blocks": InformationBlocks,
    "formulate_claims": ClaimFormulation,
    "find_knowledge": KnowledgeRetrieval,
    "select_entries": KnowledgeSelection,
    "propose_changes": KnowledgeChanges,
    "prepare_writing": WritingPoints,
    "draft_text": WritingDraft,
}
OUTPUT_SCHEMAS = {
    "extract_text": "extraction.v3",
    "segment_blocks": "blocks.v1",
    "formulate_claims": "claims.v1",
    "find_knowledge": "retrieval.v1",
    "select_entries": "selection.v1",
    "propose_changes": "proposals.v1",
    "prepare_writing": "writing_points.v1",
    "draft_text": "draft.v1",
}
STEP_PARAMETERS = {
    "extract_text": {"document_provider", "service_url", "literature_provider"},
    "segment_blocks": {"mode", "max_characters"},
    "formulate_claims": set(),
    "find_knowledge": {"query", "limit"},
    "select_entries": {"query"},
    "propose_changes": {"note_prompt_name", "note_prompt_revision"},
    "prepare_writing": {"goal"},
    "draft_text": set(),
}


def validate_step_parameters(recipe: Recipe) -> None:
    """Reject unsupported settings instead of silently ignoring experimental controls."""
    unknown = set(recipe.parameters) - STEP_PARAMETERS[recipe.step]
    if unknown:
        raise ValueError(f"Unsupported parameters for {recipe.step}: {', '.join(sorted(unknown))}")
    if recipe.step == "extract_text":
        validate_paper_parameters(recipe.parameters)
    for name in ("query", "goal"):
        if name in recipe.parameters and not isinstance(recipe.parameters[name], str):
            raise ValueError(f"{name} must be text")
    for name, minimum, maximum in (("limit", 1, 40), ("max_characters", 1, 120000)):
        if name not in recipe.parameters:
            continue
        value = recipe.parameters[name]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
    mode = recipe.parameters.get("mode", "paragraphs")
    if not isinstance(mode, str) or mode not in {"paragraphs", "model"}:
        raise ValueError("Segmentation mode must be paragraphs or model")


def claim_source_pins(
    proposal: ExtractedClaim, blocks: InformationBlocks, extraction: TextExtraction
) -> GroundedClaim:
    """Resolve an exact claim quote only within previously validated block source spans."""
    validate_blocks(blocks, extraction)
    indexes, sources = [], []
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
    return GroundedClaim(proposal=proposal, block_indexes=sorted(set(indexes)), sources=sources)


def formulate_claims(
    extraction: TextExtraction,
    blocks: InformationBlocks,
    recipe: Recipe,
    output_directory: Path,
    cancelled: Callable[[], bool],
) -> ClaimFormulation:
    """Use production import extraction with pinned information blocks as additional input."""
    validate_blocks(blocks, extraction)
    extractions = extract_document(
        list(extraction.pages),
        output_directory,
        instructions=recipe_prompt(recipe),
        configuration=recipe.model,
        cancelled=cancelled,
        blocks_packet=blocks.model_dump(mode="json"),
        validate=lambda result: validate_article_blocks(result, blocks, extraction),
    )
    claims = [
        claim_source_pins(claim, blocks, extraction)
        for article in extractions
        for claim in article.claims
    ]
    return ClaimFormulation(extractions=extractions, claims=claims)


def validate_article_blocks(
    article: ArticleExtraction, blocks: InformationBlocks, extraction: TextExtraction
) -> None:
    """Recheck claim provenance inside the shared import adapter's repair boundary."""
    for claim in article.claims:
        claim_source_pins(claim, blocks, extraction)


def recipe_prompt(recipe: Recipe) -> str:
    """Resolve the recipe's immutable prompt from the canonical configuration registry."""
    text = get_revision("prompt", recipe.prompt_name, recipe.prompt_revision).payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Recipe prompt requires nonempty text")
    return text


def selected_records(inputs: dict[str, dict], knowledge: list[Record]) -> list[Record]:
    """Verify selected candidates against both retrieval and the pinned input knowledge."""
    retrieval = KnowledgeRetrieval.model_validate(inputs["find_knowledge"])
    selection = KnowledgeSelection.model_validate(inputs["select_entries"])
    validate_selection(selection, retrieval)
    for hit in retrieval.hits:
        if hit.record not in knowledge:
            raise ValueError("Retrieved record differs from pinned input knowledge")
    selected = [entry.reference for entry in selection.entries if entry.selected]
    return [record for record in knowledge if record.reference() in selected]


def propose_changes(
    inputs: dict[str, dict],
    knowledge: list[Record],
    recipe: Recipe,
    output_directory: Path,
    cancelled: Callable[[], bool],
) -> KnowledgeChanges:
    """Reuse production matching and note validation, keeping all proposals unaccepted."""
    records = selected_records(inputs, knowledge)
    candidates = [record for record in records if record.kind == "claim"]
    formulation = ClaimFormulation.model_validate(inputs["formulate_claims"])
    extraction = TextExtraction.model_validate(inputs["extract_text"])
    blocks = InformationBlocks.model_validate(inputs["segment_blocks"])
    changes = []
    for claim in formulation.claims:
        check_cancelled(cancelled)
        if claim_source_pins(claim.proposal, blocks, extraction) != claim:
            raise ValueError("Claim provenance differs from its pinned source blocks")
        decision = propose_matching(
            claim.proposal,
            candidates,
            output_directory,
            instructions=recipe_prompt(recipe),
            configuration=recipe.model,
            cancelled=cancelled,
        )
        changes.append(ClaimChange(claim=claim, decision=decision))
    return KnowledgeChanges(
        claims=changes,
        notes=propose_selected_notes(records, recipe, output_directory, cancelled),
        warnings=[
            "Proposals only; grounding and human review are required before acceptance.",
            "Note proposals use selected knowledge; new evidence is not yet accepted into notes.",
            "Claim scope uses the text contract; structured scope migration remains pending.",
        ],
    )


def propose_selected_notes(
    records: list[Record], recipe: Recipe, output_directory: Path, cancelled: Callable[[], bool]
) -> list[NoteChange]:
    """Generate diffs only for explicitly selected notes using a pinned consolidation prompt."""
    notes = []
    note_prompt_name = recipe.parameters.get("note_prompt_name")
    note_prompt_revision = recipe.parameters.get("note_prompt_revision")
    for record in records:
        if not isinstance(record.payload, Note):
            continue
        if not isinstance(note_prompt_name, str) or not isinstance(note_prompt_revision, int):
            raise ValueError("Note proposals require a pinned note_prompt_name and revision")
        note_prompt = get_revision("prompt", note_prompt_name, note_prompt_revision).payload["text"]
        if not isinstance(note_prompt, str):
            raise ValueError("Note prompt must contain text")
        check_cancelled(cancelled)
        command = propose_note_revision(
            record,
            records,
            output_directory,
            instructions=note_prompt,
            configuration=recipe.model,
            cancelled=cancelled,
        )
        body = command.proposal.note.body if command.proposal.note else record.payload.body
        diff = "\n".join(
            difflib.unified_diff(
                record.payload.body.splitlines(),
                body.splitlines(),
                fromfile="before",
                tofile="proposal",
            )
        )
        notes.append(NoteChange(command=command, diff=diff))
    return notes


def execute_step(
    step: str,
    pdf: Path,
    inputs: dict[str, dict],
    knowledge: list[Record],
    recipe: Recipe,
    output_directory: Path,
    cancelled: Callable[[], bool],
) -> Contract:
    """Execute exactly one shared operation against explicitly supplied input revisions."""
    if step not in STEP_DEPENDENCIES or recipe.step != step:
        raise ValueError("Recipe does not match a supported step")
    if recipe.output_schema != OUTPUT_SCHEMAS[step]:
        raise ValueError("Recipe output schema does not match the step's supported format")
    validate_step_parameters(recipe)
    if any(dependency not in inputs for dependency in STEP_DEPENDENCIES[step]):
        raise ValueError("Step is missing required input revisions")
    check_cancelled(cancelled)
    if step == "extract_text":
        return extract_paper_document(
            pdf,
            recipe.parameters,
            output_directory,
            cancelled=cancelled,
            timeout_seconds=recipe.model.timeout_seconds,
        )
    if step in {"find_knowledge", "select_entries", "propose_changes"}:
        return execute_knowledge_step(step, inputs, knowledge, recipe, output_directory, cancelled)
    extraction = TextExtraction.model_validate(inputs["extract_text"])
    if step == "segment_blocks":
        return segment_step(extraction, recipe, output_directory, cancelled)
    blocks = InformationBlocks.model_validate(inputs["segment_blocks"])
    validate_blocks(blocks, extraction)
    if step == "formulate_claims":
        return formulate_claims(extraction, blocks, recipe, output_directory, cancelled)
    return execute_writing_step(
        step, extraction, blocks, inputs, recipe, output_directory, cancelled
    )


def segment_step(
    extraction: TextExtraction,
    recipe: Recipe,
    output_directory: Path,
    cancelled: Callable[[], bool],
) -> InformationBlocks:
    """Choose explicit verbatim paragraphs or source-validated model segmentation."""
    mode = recipe.parameters.get("mode", "paragraphs")
    maximum = recipe.parameters.get("max_characters", 2000)
    if not isinstance(maximum, int):
        raise ValueError("max_characters must be an integer")
    if mode == "paragraphs":
        return segment_verbatim(extraction, maximum)
    if mode != "model":
        raise ValueError("Segmentation mode must be paragraphs or model")
    return segment_information(
        extraction, recipe_prompt(recipe), output_directory, recipe.model, cancelled, maximum
    )


def execute_knowledge_step(
    step: str,
    inputs: dict[str, dict],
    knowledge: list[Record],
    recipe: Recipe,
    output_directory: Path,
    cancelled: Callable[[], bool],
) -> Contract:
    """Keep retrieval, candidate selection and proposed actions independently callable."""
    claims = ClaimFormulation.model_validate(inputs["formulate_claims"])
    query = str(
        recipe.parameters.get("query")
        or " ".join(
            f"{claim.proposal.proposition} {claim.proposal.scope}" for claim in claims.claims
        )
        or " ".join(article.bibliography.title for article in claims.extractions)
    )
    if step == "find_knowledge":
        limit = recipe.parameters.get("limit", 20)
        if not isinstance(limit, int):
            raise ValueError("Retrieval limit must be an integer")
        return retrieve_knowledge(query, knowledge, limit)
    if step == "select_entries":
        return select_knowledge(
            KnowledgeRetrieval.model_validate(inputs["find_knowledge"]),
            query,
            recipe_prompt(recipe),
            output_directory,
            recipe.model,
            cancelled,
        )
    return propose_changes(inputs, knowledge, recipe, output_directory, cancelled)


def execute_writing_step(
    step: str,
    extraction: TextExtraction,
    blocks: InformationBlocks,
    inputs: dict[str, dict],
    recipe: Recipe,
    output_directory: Path,
    cancelled: Callable[[], bool],
) -> Contract:
    """Compose cited points or prose using the same original evidence and saved rules."""
    if step == "prepare_writing":
        goal = recipe.parameters.get("goal", "")
        if not isinstance(goal, str):
            raise ValueError("Writing goal must be text")
        return prepare_writing_points(
            goal,
            extraction,
            blocks,
            {key: inputs[key] for key in ("formulate_claims", "propose_changes")},
            recipe_prompt(recipe),
            output_directory,
            recipe.model,
            cancelled,
        )
    if not recipe.author_rules_name or recipe.author_rules_revision is None:
        raise ValueError("Save and select private author rules before drafting prose")
    rules = get_revision("author_rules", recipe.author_rules_name, recipe.author_rules_revision)
    return draft_prose(
        WritingPoints.model_validate(inputs["prepare_writing"]),
        extraction,
        blocks,
        rules.payload,
        recipe_prompt(recipe),
        output_directory,
        recipe.model,
        cancelled,
    )
