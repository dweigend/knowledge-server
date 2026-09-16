"""Generate citation-preserving note revision proposals.

This module selects and validates the exact proposal context without importing
database services or the workflow that accepts and persists a revision.
"""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Final, Literal

from pydantic import Field

from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.knowledge_domain import note_citation_rules
from knowledge.model_integration import prompt_registry, structured_generation

MAX_PACKET_CHARACTERS: Final[int] = 120000


class NoteRevision(models.Contract):
    """Describe a useful note improvement or explain why the existing text should stay."""

    action: Literal["keep", "revise"]
    rationale: str = Field(min_length=1)
    note: models.Note | None


class ConsolidateNote(models.Contract):
    """Pin the target and all supplied context before accepting a note revision."""

    target: models.Reference
    context: list[models.Reference]
    proposal: NoteRevision


def validate_note_revision(
    proposal: NoteRevision, target: models.Record, records: list[models.Record]
) -> None:
    """Require preserved citations, note identity and references from supplied context."""
    if proposal.action == "keep":
        if proposal.note is not None:
            raise ValueError("Keep requires note=null")
        return
    note = proposal.note
    previous = target.payload
    assert isinstance(previous, models.Note)
    if note is None or note.kind != previous.kind:
        raise ValueError("Revision requires a note with the existing kind")
    allowed = [record.reference() for record in records] + previous.references
    if any(reference not in allowed for reference in note.references):
        raise ValueError("Note cites an unseen record")
    if any(reference.entity_id == target.entity_id for reference in note.references):
        raise ValueError("A note cannot cite itself")
    note_citation_rules.validate_note_citations(note)
    validate_preserved_citations(previous, note)


def validate_preserved_citations(previous: models.Note, note: models.Note) -> None:
    """Retain cited entities while allowing their supplied revisions to advance."""
    for reference in previous.references:
        if not any(
            candidate.entity_id == reference.entity_id and candidate.revision >= reference.revision
            for candidate in note.references
        ):
            raise ValueError("Preserve previous referenced entities without reverting revisions")
    pattern = r"\[([0-9a-f-]{36})@(\d+)\]"
    current_citations = re.findall(pattern, note.body)
    for entity_id, revision in re.findall(pattern, previous.body):
        if not any(
            candidate_id == entity_id and int(candidate_revision) >= int(revision)
            for candidate_id, candidate_revision in current_citations
        ):
            raise ValueError("Preserve existing inline citations using the same or newer revision")


def propose_note_revision(
    target: models.Record,
    records: list[models.Record],
    run_directory: Path,
    *,
    instructions: str | None = None,
    configuration: structured_generation.ModelConfiguration | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ConsolidateNote:
    """Generate a validated proposal with the exact supplied context revisions."""
    supplied = note_context(target, records)
    packet = note_packet(target, supplied, records)
    if instructions is None:
        instructions, default_configuration = prompt_registry.operation_configuration(
            "propose_changes", secondary_prompt=True
        )
        configuration = configuration or default_configuration
    proposal = structured_generation.generate(
        instructions,
        packet,
        NoteRevision,
        run_directory / "proposals",
        lambda result: validate_note_revision(result, target, supplied),
        configuration=configuration,
        cancelled=cancelled,
    )
    return ConsolidateNote(
        target=target.reference(),
        proposal=proposal,
        context=[record.reference() for record in supplied],
    )


def note_context(target: models.Record, records: list[models.Record]) -> list[models.Record]:
    """Select all claim assessments and complete evidence for the target's linked claims."""
    note = target.payload
    assert isinstance(note, models.Note)
    referenced = {reference.entity_id for reference in note.references}
    linked_claims = set(referenced)
    for record in records:
        if record.entity_id in referenced and isinstance(
            record.payload, (models.Evidence, models.Assessment)
        ):
            linked_claims.add(record.payload.claim.entity_id)
    cited = set(re.findall(r"\[([0-9a-f-]{36})@\d+\]", note.body))
    selected = []
    for record in records:
        payload = record.payload
        if (
            record.kind in {"claim", "assessment"}
            or (
                isinstance(payload, models.Evidence)
                and (
                    str(record.entity_id) in cited
                    or (note.kind != "wiki" and payload.claim.entity_id in linked_claims)
                )
            )
            or (
                isinstance(payload, models.Note)
                and record.entity_id != target.entity_id
                and payload.kind in {"permanent", "wiki"}
            )
        ):
            selected.append(record)
    return selected


def note_packet(
    target: models.Record, supplied: list[models.Record], records: list[models.Record]
) -> str:
    """Expose selected evidence and explicit omissions without truncating scientific records."""
    related_notes = [
        {
            "reference": record.reference().model_dump(mode="json"),
            "title": record.payload.title,
            "summary": record.payload.body[:500],
        }
        for record in supplied
        if isinstance(record.payload, models.Note)
        and record.entity_id != target.entity_id
        and record.payload.kind in {"permanent", "wiki"}
    ]
    packet = json.dumps(
        {
            "target": target.model_dump(mode="json"),
            "knowledge": [
                record.model_dump(mode="json")
                for record in supplied
                if record.kind in {"claim", "evidence", "assessment"}
            ],
            "related_notes": related_notes,
            "coverage": {
                "method": "All claims and assessments. Wiki: inline-cited evidence only. "
                "Other notes: complete evidence of linked claims plus inline-cited evidence. "
                "Other evidence quotations are not supplied; cite the assessment for its "
                "synthesis, never invent unseen quotations. Related notes are navigation only; "
                "their summaries are limited to 500 characters.",
                "evidence_supplied": sum(record.kind == "evidence" for record in supplied),
                "evidence_total": sum(record.kind == "evidence" for record in records),
            },
        },
        ensure_ascii=False,
    )
    if len(packet) > MAX_PACKET_CHARACTERS:
        raise ValueError("Consolidation context exceeds budget; narrow retrieval before generation")
    return packet
