"""Check passage attribution separately from evidence strength and claim matching."""

import json
from pathlib import Path

from knowledge.contracts import Claim, Contract, Evidence, ExtractedClaim, Source, Text
from knowledge.generation import generate
from knowledge.run_log import record_event


class PassageCheck(Contract):
    """Flag unsupported wording without claiming to establish scientific truth."""

    grounded: bool
    reason: Text


def check_passage(
    claim: Claim,
    relation: Evidence | ExtractedClaim,
    source: Source,
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
    prompt = Path(__file__).with_name("prompts") / "grounding.md"
    result = generate(prompt.read_text(), packet, PassageCheck, run_directory / "proposals")
    record_event(
        run_directory,
        "passage_check",
        claim=claim.proposition,
        grounded=result.grounded,
        reason=result.reason,
    )
    return result
