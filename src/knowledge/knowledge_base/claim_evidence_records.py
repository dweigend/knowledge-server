"""Create claims and evidence links under revision-safe ownership rules.

The operations validate structural relationships and persistence boundaries
without treating a valid record as scientifically true.
"""

from collections.abc import Iterable

from knowledge.knowledge_base import source_records as sources
from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.revision_store import postgresql_revision_store as store


def propose_claim(
    ledger: store.Ledger, batch_id: str, claim: models.Claim, actor: str
) -> models.Reference:
    """Store an unreviewed claim without treating it as established truth."""
    return ledger.append(batch_id, "claim", claim, actor)


def link(
    ledger: store.Ledger, batch_id: str, evidence: models.Evidence, actor: str
) -> models.Reference:
    """Deduplicate exact evidence by original PDF version, preserving its existing source pin."""
    ledger.require(evidence.claim, batch_id, "claim")
    sources.verify_quote(
        ledger,
        batch_id,
        evidence.source,
        evidence.page,
        evidence.quote,
        evidence.extraction_revision,
        evidence.block_id,
    )
    source = ledger.require(evidence.source, batch_id, "source").payload
    assert isinstance(source, models.Source)
    for existing in ledger.list(batch_id, "evidence"):
        payload = existing.payload
        if not isinstance(payload, models.Evidence):
            continue
        identity = ("claim", "page", "quote", "relation", "extraction_revision", "block_id")
        if evidence.extraction_revision is not None and payload.source != evidence.source:
            continue
        if not all(getattr(payload, field) == getattr(evidence, field) for field in identity):
            continue
        original = ledger.require(payload.source, batch_id, "source").payload
        assert isinstance(original, models.Source)
        if original.sha256 == source.sha256:
            return existing.reference()
    return ledger.append(batch_id, "evidence", evidence, actor)


def records_for_claim(
    records: Iterable[models.Record], claim: models.Reference
) -> list[models.Record]:
    """Select evidence for exactly this claim revision, preserving record order."""
    return [
        record
        for record in records
        if isinstance(record.payload, models.Evidence) and record.payload.claim == claim
    ]


def for_claim(
    ledger: store.Ledger, batch_id: str, claim: models.Reference
) -> list[models.Reference]:
    """Return current evidence references for the specified claim revision."""
    return [
        record.reference() for record in records_for_claim(ledger.list(batch_id, "evidence"), claim)
    ]
