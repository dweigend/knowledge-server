"""Reconcile extracted claims with existing knowledge candidates.

The workflow validates reuse, creation, and skip decisions before applying
revision-safe application commands.
"""

from pathlib import Path
from typing import Final

from pydantic import JsonValue

from knowledge.knowledge_base import claim_evidence_records, knowledge_service, source_records
from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.revision_store import postgresql_revision_store
from knowledge.runtime_support import workflow_event_log
from knowledge.source_workflows import claim_matching, knowledge_candidate_selection
from knowledge.source_workflows.passage_grounding import check_passage

CANDIDATE_LIMIT: Final[int] = 40
RECONCILE_ACTOR: Final[str] = "hermes:reconcile-v1"


class ReconcileClaim(models.Contract):
    """Pin an extracted passage and the reviewed matching decision for atomic import."""

    source: models.Reference
    proposal: models.ExtractedClaim
    decision: claim_matching.ClaimDecision


def claim_candidates(
    application: knowledge_service.Knowledge, batch_id: str, query: str | None = None
) -> list[models.Record]:
    """Retrieve bounded claim candidates with the same lexical operation as the workbench."""
    with application.database.transaction() as ledger:
        candidates = ledger.list(batch_id, "claim")
    if query is not None:
        retrieval = knowledge_candidate_selection.retrieve_knowledge(
            query, candidates, CANDIDATE_LIMIT
        )
        return [hit.record for hit in retrieval.hits]
    if len(candidates) > CANDIDATE_LIMIT:
        raise ValueError("Supply a retrieval query when the claim candidate budget exceeds 40")
    return candidates


def reconcile_claim(
    application: knowledge_service.Knowledge,
    batch_id: str,
    source: models.Reference,
    proposal: models.ExtractedClaim,
    run_directory: Path,
    request_id: str,
) -> list[models.Reference]:
    """Request one matching decision and apply its validated result once."""
    with application.database.transaction() as ledger:
        receipt = ledger.get_receipt(request_id)
    if receipt:
        return receipt.result
    query = f"{proposal.proposition} {proposal.scope}"
    candidates = claim_candidates(application, batch_id, query)
    decision = claim_matching.propose_matching(proposal, candidates, run_directory)
    matching_decision = decision.model_dump(mode="json")
    decision = check_claim_grounding(application, source, proposal, decision, run_directory)
    command = ReconcileClaim(source=source, proposal=proposal, decision=decision)
    return accept_claim_decision(
        application, batch_id, command, matching_decision, run_directory, request_id
    )


def accept_claim_decision(
    application: knowledge_service.Knowledge,
    batch_id: str,
    command: ReconcileClaim,
    matching_decision: dict[str, JsonValue],
    run_directory: Path,
    request_id: str,
) -> list[models.Reference]:
    """Accept the grounded decision atomically and audit its original matching result."""
    references = application.database.command(
        request_id,
        batch_id,
        "reconcile",
        command,
        RECONCILE_ACTOR,
        lambda ledger: apply_claim_decision(ledger, batch_id, command),
    )
    workflow_event_log.record_event(
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


def apply_claim_decision(
    ledger: postgresql_revision_store.Ledger, batch_id: str, command: ReconcileClaim
) -> list[models.Reference]:
    """Reuse a claim without changing its meaning and deduplicate exact evidence."""
    decision = command.decision
    claim_matching.validate_decision(decision, ledger.list(batch_id, "claim"))
    if decision.action == "skip":
        return []
    actor = RECONCILE_ACTOR
    target = decision.target
    if target is None:
        claim = models.Claim.model_validate(
            command.proposal.model_dump(include={"proposition", "scope", "qualifications"})
        )
        target = claim_evidence_records.propose_claim(ledger, batch_id, claim, actor)
    relation = models.Evidence(
        claim=target,
        source=command.source,
        **command.proposal.model_dump(exclude={"proposition", "scope", "qualifications"}),
    )
    if decision.action == "reuse":
        relation.relation = decision.relation
        relation.rationale = decision.rationale
        relation.directness = decision.directness
    return [target, claim_evidence_records.link(ledger, batch_id, relation, actor)]


def check_claim_grounding(
    application: knowledge_service.Knowledge,
    source_reference: models.Reference,
    proposal: models.ExtractedClaim,
    decision: claim_matching.ClaimDecision,
    run_directory: Path,
) -> claim_matching.ClaimDecision:
    """Keep failed attribution checks as logged proposals instead of storing dubious claims."""
    if decision.action == "skip":
        return decision
    with application.database.transaction() as ledger:
        record = ledger.get(source_reference.entity_id, source_reference.revision)
        source = ledger.require(source_reference, record.batch_id, "source").payload
        source_records.verify_quote(
            ledger, record.batch_id, source_reference, proposal.page, proposal.quote
        )
        target = (
            ledger.require(decision.target, record.batch_id, "claim").payload
            if decision.target
            else None
        )
    assert isinstance(source, models.Source)
    claim = (
        target
        if isinstance(target, models.Claim)
        else models.Claim.model_validate(
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
