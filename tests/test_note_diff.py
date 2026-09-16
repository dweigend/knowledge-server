"""Keep title-only and citation-only edits visible in the review log."""

from uuid import uuid4

from knowledge.knowledge_domain.knowledge_record_models import Note, Reference
from knowledge.source_workflows.note_consolidation import note_diff


def test_note_diff_shows_title_and_reference_changes() -> None:
    reference = Reference(entity_id=uuid4(), revision=1)
    previous = Note(kind="permanent", title="Before", body="Same body", references=[reference])
    replacement = previous.model_copy(
        update={
            "title": "After",
            "references": [reference.model_copy(update={"revision": 2})],
        }
    )
    diff = note_diff(previous, replacement, Reference(entity_id=uuid4(), revision=1))
    assert "-# Before" in diff
    assert "+# After" in diff
    assert f"- {reference.entity_id}@1" in diff
    assert f"- {reference.entity_id}@2" in diff
    assert note_diff(previous, None, reference) == ""
