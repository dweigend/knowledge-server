"""Prepare cited writing points and draft prose from pinned evidence.

Both steps validate block references and keep author rules separate from source
evidence so examples cannot silently become factual support.
"""

from collections.abc import Mapping

from knowledge.experiments import pipeline_specification
from knowledge.experiments.experiment_steps import parameter_models
from knowledge.source_workflows import source_grounded_writing


def validate_writing_parameters(parameters: Mapping[str, object]) -> None:
    """Validate the optional writing goal."""
    parameter_models.OPTIONAL_TEXT.validate_python(parameters.get("goal"))


def prepare_writing(
    execution: pipeline_specification.StepExecution,
) -> source_grounded_writing.WritingPoints:
    """Compose cited points from pinned proposals and source blocks."""
    goal = parameter_models.OPTIONAL_TEXT.validate_python(execution.recipe.parameters.get("goal"))
    extraction = execution.inputs.extract_text
    blocks = execution.inputs.segment_blocks
    claims = execution.inputs.formulate_claims
    changes = execution.inputs.propose_changes
    assert extraction is not None and blocks is not None
    assert claims is not None and changes is not None
    return source_grounded_writing.prepare_writing_points(
        goal or "",
        extraction,
        blocks,
        {
            "formulate_claims": claims.model_dump(mode="json"),
            "propose_changes": changes.model_dump(mode="json"),
        },
        execution.prompt_text,
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
    points = execution.inputs.prepare_writing
    extraction = execution.inputs.extract_text
    blocks = execution.inputs.segment_blocks
    assert points is not None and extraction is not None and blocks is not None
    return source_grounded_writing.draft_prose(
        points,
        extraction,
        blocks,
        execution.author_rules.model_dump(mode="json"),
        execution.prompt_text,
        recipe.model,
        execution.cancelled,
    )
