"""Immutable source registration and exact PDF-page evidence validation."""

from knowledge.contracts import LegacySource, Record, Reference, Source, ZoteroReference
from knowledge.document_extraction import get_snapshot
from knowledge.storage import Ledger


def register(ledger: Ledger, batch_id: str, source: Source, actor: str) -> Reference:
    """Register a source once per batch, identified by its original PDF hash."""
    if isinstance(source, LegacySource):
        raise ValueError("Legacy sources are read-only; register a verified Zotero source")
    if source.sha256 != source.zotero.original_sha256:
        raise ValueError("Source checksum must match its pinned Zotero original PDF")
    already_registered = any(
        isinstance(existing.payload, Source) and existing.payload.sha256 == source.sha256
        for existing in ledger.list(batch_id, "source")
    )
    if already_registered:
        raise ValueError("Source already registered in this batch; reuse its request receipt")
    return ledger.append(batch_id, "source", source, actor)


def verify_quote(
    ledger: Ledger,
    batch_id: str,
    reference: Reference,
    page: int,
    quote: str,
    extraction_revision: int | None = None,
    block_id: str | None = None,
) -> None:
    """Check pinned extraction prose or the legacy immutable page-text contract."""
    source = ledger.require(reference, batch_id, "source").payload
    assert isinstance(source, Source)
    if (extraction_revision is None) != (block_id is None):
        raise ValueError("Evidence requires both extraction_revision and block_id")
    if extraction_revision is not None and block_id is not None:
        verify_block_quote(ledger, reference, extraction_revision, block_id, page, quote)
        return
    if page < 1 or page > len(source.pages) or not quote or quote not in source.pages[page - 1]:
        raise ValueError("Quote must be an exact substring of the registered PDF page")


def verify_block_quote(
    ledger: Ledger, reference: Reference, revision: int, block_id: str, page: int, quote: str
) -> None:
    """Accept only exact, unflagged prose from one pinned extraction page."""
    snapshot = get_snapshot(ledger, reference, revision)
    if snapshot is None:
        raise ValueError("The cited extraction revision does not exist")
    matches = [block for block in snapshot.blocks if block.id == block_id]
    if len(matches) != 1:
        raise ValueError("The cited extraction block is missing or ambiguous")
    block = matches[0]
    if block.kind not in {"text", "abstract", "paragraph", "list_item", "listitem", "footnote"}:
        raise ValueError("Evidence requires source prose; tables and page furniture need review")
    if block.issues:
        raise ValueError("The cited extraction block has unresolved quality issues")
    if block.page != page or any(location.page != page for location in block.locations):
        raise ValueError("Evidence must cite one original page of its extraction block")
    if not quote or quote not in block.text:
        raise ValueError("Quote must be an exact substring of the pinned extraction block")


def zotero_reference(ledger: Ledger, record: Record) -> ZoteroReference:
    """Resolve historical citations through the migrated revision of the same PDF."""
    source = record.payload
    if not isinstance(source, Source):
        raise ValueError("Record is not a source")
    if not isinstance(source, LegacySource):
        return source.zotero
    current = ledger.get(record.entity_id)
    for revision in range(current.revision, record.revision, -1):
        candidate = ledger.get(record.entity_id, revision).payload
        if isinstance(candidate, LegacySource) or not isinstance(candidate, Source):
            continue
        if candidate.sha256 == source.sha256:
            return candidate.zotero
    raise ValueError("Historical PDF version has no verified Zotero reference")
