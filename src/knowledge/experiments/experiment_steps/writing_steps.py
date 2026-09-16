"""Prepare cited writing points and draft prose from pinned evidence.

Both steps validate block references and keep author rules separate from source
evidence so examples cannot silently become factual support.
"""

from typing import cast

from knowledge.experiments import pipeline_specification
from knowledge.source_workflows import source_grounded_writing


def validate_writing_parameters(parameters: dict) -> None:
    """Validate the optional writing goal."""
    goal = parameters.get("goal")
    if goal is not None and not isinstance(goal, str):
        raise ValueError("goal must be text")


def prepare_writing(
    execution: pipeline_specification.StepExecution,
) -> source_grounded_writing.WritingPoints:
    """Compose cited points from pinned proposals and source blocks."""
    goal = cast(str, execution.recipe.parameters.get("goal", ""))
    return source_grounded_writing.prepare_writing_points(
        goal,
        execution.inputs["extract_text"],
        execution.inputs["segment_blocks"],
        {
            "formulate_claims": execution.inputs["formulate_claims"].model_dump(mode="json"),
            "propose_changes": execution.inputs["propose_changes"].model_dump(mode="json"),
        },
        execution.prompt_text,
        execution.output_directory,
        execution.recipe.model,
        execution.cancelled,
    )


def draft_text(
    execution: pipeline_specification.StepExecution,
) -> source_grounded_writing.WritingDraft:
    """Draft prose from cited points using explicitly pinned author rules."""
    recipe = execution.recipe
    if (
        not recipe.author_rules_name
        or recipe.author_rules_revision is None
        or execution.author_rules is None
    ):
        raise ValueError("Save and select private author rules before drafting prose")
    return source_grounded_writing.draft_prose(
        execution.inputs["prepare_writing"],
        execution.inputs["extract_text"],
        execution.inputs["segment_blocks"],
        execution.author_rules,
        execution.prompt_text,
        execution.output_directory,
        recipe.model,
        execution.cancelled,
    )
