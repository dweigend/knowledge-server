"""Record assessments, human decisions, and derived review status.

Review results pin their dependencies so later revisions can be detected and
presented for renewed review.
"""

from collections import Counter
from collections.abc import Iterable
from uuid import UUID

from knowledge.knowledge_base import claim_evidence_records as evidence
from knowledge.knowledge_domain import (
    application_errors as errors,
)
from knowledge.knowledge_domain import (
    knowledge_record_models as models,
)
from knowledge.revision_store import postgresql_revision_store as store


def reference_identities(references: Iterable[models.Reference]) -> list[tuple[UUID, int]]:
    """Extract record identities without depending on their string representation."""
    return [(reference.entity_id, reference.revision) for reference in references]


def direct_dependencies(ledger: store.Ledger, record: models.Record) -> list[models.Reference]:
    """Read the immediate references that determine a record’s review state."""
    payload = record.payload
    if record.kind == "claim":
        return evidence.for_claim(ledger, record.batch_id, record.reference())
    if isinstance(payload, models.Assessment):
        return [payload.claim, *payload.evidence]
    if isinstance(payload, models.Evidence):
        return [payload.claim, payload.source]
    if isinstance(payload, models.Note):
        return payload.references
    return []


def dependencies(ledger: store.Ledger, record: models.Record) -> list[models.Reference]:
    """Resolve a finite transitive set, including the current evidence for claims."""
    result: dict[tuple[str, int], models.Reference] = {}
    visited = {(str(record.entity_id), record.revision)}
    pending = [record]
    while pending:
        current = pending.pop()
        direct = direct_dependencies(ledger, current)
        for reference in direct:
            key = (str(reference.entity_id), reference.revision)
            if key in visited:
                continue
            visited.add(key)
            result[key] = reference
            pending.append(ledger.require(reference, record.batch_id))
    return list(result.values())


def is_current(ledger: store.Ledger, record: models.Record) -> bool:
    """Check record revisions and evidence membership before reusing a review."""
    if not revision_is_current(record, ledger.get(record.entity_id)):
        return False
    payload = record.payload
    if isinstance(payload, models.Assessment):
        existing = evidence.for_claim(ledger, record.batch_id, payload.claim)
        if set(reference_identities(existing)) != set(reference_identities(payload.evidence)):
            return False
    for reference in dependencies(ledger, record):
        child = ledger.get(reference.entity_id, reference.revision)
        if not revision_is_current(child, ledger.get(reference.entity_id)):
            return False
        if isinstance(child.payload, models.Assessment) and not is_current(ledger, child):
            return False
    return True


def propose_assessment(
    ledger: store.Ledger,
    batch_id: str,
    assessment: models.Assessment,
    actor: str,
    expected: models.Reference | None = None,
) -> models.Reference:
    """Validate ownership, evidence completeness and balance before appending."""
    ledger.require(assessment.claim, batch_id, "claim")
    validate_assessment_target(ledger, batch_id, assessment, expected)
    complete = evidence.for_claim(ledger, batch_id, assessment.claim)
    if Counter(reference_identities(complete)) != Counter(
        reference_identities(assessment.evidence)
    ):
        raise ValueError("Assessment must include every current evidence relation for its claim")
    relations = assessment_relations(ledger, batch_id, assessment)
    validate_balance(assessment, relations)
    return ledger.append(batch_id, "assessment", assessment, actor, expected)


def record_decision(
    ledger: store.Ledger,
    batch_id: str,
    target: models.Reference,
    verdict: str,
    comment: str,
    actor: str,
) -> models.Reference:
    """Record a human verdict only for a current target and its dependencies."""
    if not actor.startswith("human:"):
        raise ValueError("Only the human review boundary may record decisions")
    record = ledger.require(target, batch_id)
    if record.kind == "review":
        raise ValueError("Review a knowledge record, not another review")
    if not is_current(ledger, record):
        raise errors.Conflict("Target or dependencies changed; update the proposal before review")
    decision = models.Review.model_validate(
        {
            "target": target,
            "dependencies": dependencies(ledger, record),
            "verdict": verdict,
            "comment": comment,
        }
    )
    return ledger.append(batch_id, "review", decision, actor)


def status(ledger: store.Ledger, record: models.Record) -> str:
    """Derive the review state from the latest decision and current dependencies."""
    if not is_current(ledger, record):
        return "needs_review"
    decisions = [
        candidate
        for candidate in ledger.list(record.batch_id, "review")
        if isinstance(candidate.payload, models.Review)
        and candidate.payload.target == record.reference()
    ]
    if not decisions:
        return "proposed"
    payload = max(decisions, key=lambda decision: decision.created_at).payload
    assert isinstance(payload, models.Review)
    if set(reference_identities(payload.dependencies)) != set(
        reference_identities(dependencies(ledger, record))
    ):
        return "needs_review"
    return payload.verdict


def validate_assessment_target(
    ledger: store.Ledger,
    batch_id: str,
    assessment: models.Assessment,
    expected: models.Reference | None,
) -> None:
    """Prevent an existing assessment from moving to another claim."""
    if expected is None:
        return
    previous = ledger.require(expected, batch_id, "assessment").payload
    assert isinstance(previous, models.Assessment)
    if previous.claim.entity_id != assessment.claim.entity_id:
        raise ValueError("An assessment cannot be reassigned to another claim")


def assessment_relations(
    ledger: store.Ledger, batch_id: str, assessment: models.Assessment
) -> set[models.Relation]:
    """Read the relation types from the assessment's pinned evidence."""
    relations: set[models.Relation] = set()
    for reference in assessment.evidence:
        payload = ledger.require(reference, batch_id, "evidence").payload
        assert isinstance(payload, models.Evidence)
        relations.add(payload.relation)
    return relations


def validate_balance(assessment: models.Assessment, relations: set[models.Relation]) -> None:
    """Require the evidence types implied by the selected balance."""
    required_relations = {
        "open": set(),
        "mixed": {"supports", "contradicts"},
        "mostly_supported": {"supports"},
        "mostly_contradicted": {"contradicts"},
    }
    if not required_relations[assessment.balance].issubset(relations):
        raise ValueError("Assessment balance does not match its evidence")
    if not relations and (assessment.balance != "open" or assessment.confidence != "low"):
        raise ValueError("No evidence requires open balance and low confidence")


def revision_is_current(record: models.Record, current: models.Record) -> bool:
    """Accept only unchanged revisions or the verified storage-only Zotero migration."""
    if current.revision == record.revision:
        return True
    if current.actor != "migration:zotero-ownership-v1" or current.revision != record.revision + 1:
        return False
    if not isinstance(record.payload, models.LegacySource) or not isinstance(
        current.payload, models.Source
    ):
        return False
    if isinstance(current.payload, models.LegacySource):
        return False
    legacy_content = record.payload.model_dump(
        exclude={"bibliography", "original_path", "archive_path", "zotero"}
    )
    migrated_content = current.payload.model_dump(exclude={"zotero"})
    return (
        legacy_content == migrated_content
        and current.payload.zotero.original_sha256 == record.payload.sha256
    )
