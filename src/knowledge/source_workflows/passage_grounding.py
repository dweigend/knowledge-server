"""Check whether a passage supports the claimed source attribution.

Grounding stays separate from evidence strength, claim equivalence, and human
acceptance.
"""

import json
from pathlib import Path

from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.model_integration import prompt_registry, structured_generation
from knowledge.runtime_support import workflow_event_log


class PassageCheck(models.Contract):
    """Flag unsupported wording without claiming to establish scientific truth."""

    grounded: bool
    reason: models.Text


def check_passage(
    claim: models.Claim,
    relation: models.Evidence | models.ExtractedClaim,
    source: models.Source,
    run_directory: Path,
) -> PassageCheck:
    """Compare one claim with its quote and actual page using a fresh narrow model task."""
    packet = json.dumps(
        {
            "claim": claim.model_dump(mode="json"),
            "relation": relation.relation,
            "directness": relation.directness,
            "rationale": relation.rationale,
            "quote": relation.quote,
            "page": source.pages[relation.page - 1],
            "limitations": relation.limitations,
        },
        ensure_ascii=False,
    )
    prompt = prompt_registry.load_prompt("grounding")
    result = structured_generation.generate(prompt, packet, PassageCheck)
    workflow_event_log.record_event(
        run_directory,
        "passage_check",
        claim=claim.proposition,
        grounded=result.grounded,
        reason=result.reason,
    )
    return result
