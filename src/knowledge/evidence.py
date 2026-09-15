"""Claim and evidence ownership; structural validity never implies truth."""

from collections.abc import Iterable

from knowledge import sources
from knowledge.contracts import Claim, Evidence, Record, Reference, Source
from knowledge.storage import Ledger


def propose_claim(ledger: Ledger, batch_id: str, claim: Claim, actor: str) -> Reference:
    """Store an unreviewed claim without treating it as established truth."""
    return ledger.append(batch_id, "claim", claim, actor)


def link(ledger: Ledger, batch_id: str, evidence: Evidence, actor: str) -> Reference:
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
    assert isinstance(source, Source)
    for existing in ledger.list(batch_id, "evidence"):
        payload = existing.payload
        if not isinstance(payload, Evidence):
            continue
        identity = ("claim", "page", "quote", "relation", "extraction_revision", "block_id")
        if evidence.extraction_revision is not None and payload.source != evidence.source:
            continue
        if not all(getattr(payload, field) == getattr(evidence, field) for field in identity):
            continue
        original = ledger.require(payload.source, batch_id, "source").payload
        assert isinstance(original, Source)
        if original.sha256 == source.sha256:
            return existing.reference()
    return ledger.append(batch_id, "evidence", evidence, actor)


def records_for_claim(records: Iterable[Record], claim: Reference) -> list[Record]:
    """Select evidence for exactly this claim revision, preserving record order."""
    return [
        record
        for record in records
        if isinstance(record.payload, Evidence) and record.payload.claim == claim
    ]


def for_claim(ledger: Ledger, batch_id: str, claim: Reference) -> list[Reference]:
    """Return current evidence references for the specified claim revision."""
    return [
        record.reference() for record in records_for_claim(ledger.list(batch_id, "evidence"), claim)
    ]
