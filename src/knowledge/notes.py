"""Source notes, permanent Zettel and wiki notes share revision-safe edits."""

import re

from knowledge.contracts import Note, Reference
from knowledge.storage import Ledger


def save(
    ledger: Ledger,
    batch_id: str,
    note: Note,
    actor: str,
    expected: Reference | None = None,
) -> Reference:
    """Validate pinned references and inline citations before appending a note revision."""
    for reference in note.references:
        ledger.require(reference, batch_id)
        if expected and reference.entity_id == expected.entity_id:
            raise ValueError("A note cannot reference itself")
    validate_citations(note)
    return ledger.append(batch_id, "note", note, actor, expected)


def validate_citations(note: Note) -> None:
    """Require every inline citation to appear in the note's pinned references."""
    cited = re.findall(r"\[([0-9a-f-]{36})@(\d+)\]", note.body)
    allowed = {(str(ref.entity_id), str(ref.revision)) for ref in note.references}
    if not set(cited).issubset(allowed):
        raise ValueError("Inline citation is absent from the note's pinned references")
    if note.kind == "wiki" and not cited:
        raise ValueError("Wiki prose requires inline revision citations")
