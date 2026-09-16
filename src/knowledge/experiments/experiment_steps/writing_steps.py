"""Prepare cited writing points and draft prose from pinned evidence.

Both steps validate block references and keep author rules separate from source
evidence so examples cannot silently become factual support.
"""

from knowledge.experiments import pipeline_specification
from knowledge.experiments.experiment_steps import document_steps
from knowledge.model_integration import prompt_registry
from knowledge.source_workflows import information_block_extraction, source_grounded_writing


def validate_writing_parameters(parameters: dict) -> None:
    """Validate the optional writing goal."""
    goal = parameters.get("goal")
    if goal is not None and not isinstance(goal, str):
        raise ValueError("goal must be text")


def prepare_writing(
    execution: pipeline_specification.StepExecution,
) -> source_grounded_writing.WritingPoints:
    """Compose cited points from pinned proposals and source blocks."""
    goal = execution.recipe.parameters.get("goal", "")
    if not isinstance(goal, str):
        raise ValueError("Writing goal must be text")
    extraction, blocks = _source_inputs(execution)
    return source_grounded_writing.prepare_writing_points(
        goal,
        extraction,
        blocks,
        {key: execution.inputs[key] for key in ("formulate_claims", "propose_changes")},
        document_steps.recipe_prompt(execution),
        execution.output_directory,
        execution.recipe.model,
        execution.cancelled,
    )


def draft_text(
    execution: pipeline_specification.StepExecution,
) -> source_grounded_writing.WritingDraft:
    """Draft prose from cited points using explicitly pinned author rules."""
    recipe = execution.recipe
    if not recipe.author_rules_name or recipe.author_rules_revision is None:
        raise ValueError("Save and select private author rules before drafting prose")
    extraction, blocks = _source_inputs(execution)
    rules = prompt_registry.get_revision(
        "author_rules", recipe.author_rules_name, recipe.author_rules_revision
    )
    return source_grounded_writing.draft_prose(
        source_grounded_writing.WritingPoints.model_validate(execution.inputs["prepare_writing"]),
        extraction,
        blocks,
        rules.payload,
        document_steps.recipe_prompt(execution),
        execution.output_directory,
        recipe.model,
        execution.cancelled,
    )


def _source_inputs(
    execution: pipeline_specification.StepExecution,
) -> tuple[
    information_block_extraction.TextExtraction,
    information_block_extraction.InformationBlocks,
]:
    extraction = information_block_extraction.TextExtraction.model_validate(
        execution.inputs["extract_text"]
    )
    blocks = information_block_extraction.InformationBlocks.model_validate(
        execution.inputs["segment_blocks"]
    )
    information_block_extraction.validate_blocks(blocks, extraction)
    return extraction, blocks
