"""Create and revise source, permanent, and wiki notes.

Note edits preserve expected revisions and validate every cited record reference
before persistence.
"""

from knowledge.knowledge_domain import knowledge_record_models, note_citation_rules
from knowledge.revision_store import postgresql_revision_store as store


def save(
    ledger: store.Ledger,
    batch_id: str,
    note: knowledge_record_models.Note,
    actor: str,
    expected: knowledge_record_models.Reference | None = None,
) -> knowledge_record_models.Reference:
    """Validate pinned references and inline citations before appending a note revision."""
    for reference in note.references:
        ledger.require(reference, batch_id)
        if expected and reference.entity_id == expected.entity_id:
            raise ValueError("A note cannot reference itself")
    note_citation_rules.validate_note_citations(note)
    return ledger.append(batch_id, "note", note, actor, expected)
