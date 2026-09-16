"""Propose claim matches against an explicit candidate set.

This module owns the persistence-free matching contract and generation step;
grounding and atomic acceptance remain in the reconciliation workflow.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import Field

from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.model_integration import prompt_registry, structured_generation


class ClaimDecision(models.Contract):
    """Explain whether a source passage adds evidence, a distinct claim or nothing."""

    action: Literal["reuse", "new", "skip"]
    target: models.Reference | None
    rationale: str = Field(min_length=1)
    relation: Literal["supports", "contradicts", "qualifies", "unclear"]
    directness: Literal["direct", "indirect", "unclear"] = "unclear"


def validate_decision(decision: ClaimDecision, candidates: list[models.Record]) -> None:
    """Reject invented targets and inconsistent action/target combinations."""
    if decision.action != "reuse":
        if decision.target is not None:
            raise ValueError("Only reuse may specify a target")
        return
    allowed = [candidate.reference() for candidate in candidates]
    if decision.target not in allowed:
        raise ValueError("Reuse must select a supplied claim revision")


def propose_matching(
    proposal: models.ExtractedClaim,
    candidates: list[models.Record],
    run_directory: Path,
    *,
    instructions: str | None = None,
    configuration: structured_generation.ModelConfiguration | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ClaimDecision:
    """Match one extracted claim against the exact supplied candidate revisions."""
    packet = json.dumps(
        {
            "proposal": proposal.model_dump(mode="json"),
            "candidates": [record.model_dump(mode="json") for record in candidates],
        }
    )
    if instructions is None:
        instructions, default_configuration = prompt_registry.operation_configuration(
            "propose_changes"
        )
        configuration = configuration or default_configuration
    return structured_generation.generate(
        instructions,
        packet,
        ClaimDecision,
        run_directory / "proposals",
        lambda result: validate_decision(result, candidates),
        configuration=configuration,
        cancelled=cancelled,
    )
