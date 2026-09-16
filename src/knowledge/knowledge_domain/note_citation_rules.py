"""Validate revision-pinned inline citations in knowledge notes.

The rule is persistence-independent so proposal generation and accepted note
writes enforce the same citation contract at the domain center.
"""

import re

from knowledge.knowledge_domain import knowledge_record_models as models


def validate_note_citations(note: models.Note) -> None:
    """Require every inline citation to appear in the note's pinned references."""
    cited = re.findall(r"\[([0-9a-f-]{36})@(\d+)\]", note.body)
    allowed = {(str(ref.entity_id), str(ref.revision)) for ref in note.references}
    if not set(cited).issubset(allowed):
        raise ValueError("Inline citation is absent from the note's pinned references")
    if note.kind == "wiki" and not cited:
        raise ValueError("Wiki prose requires inline revision citations")
