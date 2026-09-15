"""Match extracted claims against existing candidates before accepting new knowledge."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import Field

from knowledge import evidence, sources
from knowledge.application import Knowledge
from knowledge.contracts import Claim, Contract, Evidence, ExtractedClaim, Record, Reference, Source
from knowledge.generation import ModelConfiguration, generate
from knowledge.grounding import check_passage
from knowledge.prompt_registry import load_prompt
from knowledge.run_log import record_event
from knowledge.storage import Ledger

CANDIDATE_LIMIT = 40


class ClaimDecision(Contract):
    """Explain whether a source passage adds evidence, a distinct claim or nothing."""

    action: Literal["reuse", "new", "skip"]
    target: Reference | None
    rationale: str = Field(min_length=1)
    relation: Literal["supports", "contradicts", "qualifies", "unclear"]
    directness: Literal["direct", "indirect", "unclear"] = "unclear"


class ReconcileClaim(Contract):
    """Pin an extracted passage and the reviewed matching decision for atomic import."""

    source: Reference
    proposal: ExtractedClaim
    decision: ClaimDecision


def claim_candidates(application: Knowledge, batch_id: str) -> list[Record]:
    """Supply every claim in the bounded pilot instead of guessing lexical equivalence."""
    with application.database.transaction() as ledger:
        candidates = ledger.list(batch_id, "claim")
    if len(candidates) > CANDIDATE_LIMIT:
        raise ValueError("Pilot exceeds the claim candidate budget; add bounded retrieval first")
    return candidates


def validate_decision(decision: ClaimDecision, candidates: list[Record]) -> None:
    """Reject invented targets and inconsistent action/target combinations."""
    if decision.action != "reuse":
        if decision.target is not None:
            raise ValueError("Only reuse may specify a target")
        return
    allowed = [candidate.reference() for candidate in candidates]
    if decision.target not in allowed:
        raise ValueError("Reuse must select a supplied claim revision")


def reconcile_claim(
    application: Knowledge,
    batch_id: str,
    source: Reference,
    proposal: ExtractedClaim,
    run_directory: Path,
    request_id: str,
) -> list[Reference]:
    """Ask Luna for one matching decision and apply its validated result once."""
    with application.database.transaction() as ledger:
        receipt = ledger.get_receipt(request_id)
    if receipt:
        return [Reference.model_validate(reference) for reference in receipt["result"]]
    decision = propose_matching(proposal, claim_candidates(application, batch_id), run_directory)
    matching_decision = decision.model_dump(mode="json")
    decision = check_claim_grounding(application, source, proposal, decision, run_directory)
    command = ReconcileClaim(source=source, proposal=proposal, decision=decision)
    return accept_claim_decision(
        application, batch_id, command, matching_decision, run_directory, request_id
    )


def propose_matching(
    proposal: ExtractedClaim,
    candidates: list[Record],
    run_directory: Path,
    *,
    instructions: str | None = None,
    configuration: ModelConfiguration | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ClaimDecision:
    """Match one extracted claim against the exact supplied candidate revisions."""
    packet = json.dumps(
        {
            "proposal": proposal.model_dump(mode="json"),
            "candidates": [record.model_dump(mode="json") for record in candidates],
        }
    )
    prompt = instructions if instructions is not None else load_prompt("reconcile")
    return generate(
        prompt,
        packet,
        ClaimDecision,
        run_directory / "proposals",
        lambda result: validate_decision(result, candidates),
        configuration=configuration,
        cancelled=cancelled,
    )


def accept_claim_decision(
    application: Knowledge,
    batch_id: str,
    command: ReconcileClaim,
    matching_decision: dict,
    run_directory: Path,
    request_id: str,
) -> list[Reference]:
    """Accept the grounded decision atomically and audit its original matching result."""
    references = application.database.command(
        request_id,
        batch_id,
        "reconcile",
        command,
        "hermes:gpt-5.6-luna:reconcile-v1",
        lambda ledger: apply_claim_decision(ledger, batch_id, command),
    )
    record_event(
        run_directory,
        "claim_decision",
        request_id=request_id,
        proposal=command.proposal.proposition,
        extracted_claim=command.proposal.model_dump(mode="json"),
        source=command.source.model_dump(mode="json"),
        decision=command.decision.model_dump(mode="json"),
        matching_decision=matching_decision,
        references=[reference.model_dump(mode="json") for reference in references],
    )
    return references


def apply_claim_decision(ledger: Ledger, batch_id: str, command: ReconcileClaim) -> list[Reference]:
    """Reuse a claim without changing its meaning and deduplicate exact evidence."""
    decision = command.decision
    validate_decision(decision, ledger.list(batch_id, "claim"))
    if decision.action == "skip":
        return []
    actor = "hermes:gpt-5.6-luna:reconcile-v1"
    target = decision.target
    if target is None:
        claim = Claim.model_validate(
            command.proposal.model_dump(include={"proposition", "scope", "qualifications"})
        )
        target = evidence.propose_claim(ledger, batch_id, claim, actor)
    ledger.next_revision(batch_id, "claim", target)
    relation = Evidence(
        claim=target,
        source=command.source,
        **command.proposal.model_dump(exclude={"proposition", "scope", "qualifications"}),
    )
    if decision.action == "reuse":
        relation.relation = decision.relation
        relation.rationale = decision.rationale
        relation.directness = decision.directness
    return [target, evidence.link(ledger, batch_id, relation, actor)]


def check_claim_grounding(
    application: Knowledge,
    source_reference: Reference,
    proposal: ExtractedClaim,
    decision: ClaimDecision,
    run_directory: Path,
) -> ClaimDecision:
    """Keep failed attribution checks as logged proposals instead of storing dubious claims."""
    if decision.action == "skip":
        return decision
    with application.database.transaction() as ledger:
        record = ledger.get(source_reference.entity_id, source_reference.revision)
        source = ledger.require(source_reference, record.batch_id, "source").payload
        sources.verify_quote(
            ledger, record.batch_id, source_reference, proposal.page, proposal.quote
        )
        target = (
            ledger.require(decision.target, record.batch_id, "claim").payload
            if decision.target
            else None
        )
    assert isinstance(source, Source)
    claim = (
        target
        if isinstance(target, Claim)
        else Claim.model_validate(
            proposal.model_dump(include={"proposition", "scope", "qualifications"})
        )
    )
    relation = proposal.model_copy(
        update={
            "relation": decision.relation,
            "rationale": decision.rationale,
            "directness": decision.directness,
        }
        if decision.action == "reuse"
        else {}
    )
    check = check_passage(claim, relation, source, run_directory)
    if check.grounded:
        return decision
    return decision.model_copy(
        update={
            "action": "skip",
            "target": None,
            "rationale": "Passage check requires review: " + check.reason,
        }
    )
