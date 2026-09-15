"""Improve existing notes through bounded, citation-preserving model proposals."""

import difflib
import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from knowledge import notes, review
from knowledge.application import AssessmentCommand, Knowledge
from knowledge.contracts import Assessment, Contract, Evidence, Note, Record, Reference, Review
from knowledge.evidence import records_for_claim
from knowledge.generation import generate
from knowledge.run_log import record_event
from knowledge.storage import Ledger

MAX_PACKET_CHARACTERS = 120000


class NoteRevision(Contract):
    """Describe a useful note improvement or explain why the existing text should stay."""

    action: Literal["keep", "revise"]
    rationale: str = Field(min_length=1)
    note: Note | None


class ConsolidateNote(Contract):
    """Pin the target and all supplied context before accepting a note revision."""

    target: Reference
    context: list[Reference]
    proposal: NoteRevision


def knowledge_packet(records: list[Record]) -> list[dict]:
    """Provide claims, evidence and assessments without copying entire source texts."""
    return [
        record.model_dump(mode="json")
        for record in records
        if record.kind in {"claim", "evidence", "assessment"}
    ]


def validate_note_revision(proposal: NoteRevision, target: Record, records: list[Record]) -> None:
    """Require preserved citations, note identity and references from supplied context."""
    if proposal.action == "keep":
        if proposal.note is not None:
            raise ValueError("Keep requires note=null")
        return
    note = proposal.note
    previous = target.payload
    assert isinstance(previous, Note)
    if note is None or note.kind != previous.kind:
        raise ValueError("Revision requires a note with the existing kind")
    allowed = [record.reference() for record in records] + previous.references
    if any(reference not in allowed for reference in note.references):
        raise ValueError("Note cites an unseen record")
    if any(reference.entity_id == target.entity_id for reference in note.references):
        raise ValueError("A note cannot cite itself")
    notes.validate_citations(note)
    validate_preserved_citations(previous, note)


def validate_preserved_citations(previous: Note, note: Note) -> None:
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


def apply_note_revision(ledger: Ledger, batch_id: str, command: ConsolidateNote) -> list[Reference]:
    """Recheck context and protect human-authored or reviewed notes before writing."""
    target = ledger.require(command.target, batch_id, "note")
    for reference in [command.target, *command.context]:
        current = ledger.get(reference.entity_id)
        if current.revision != reference.revision:
            raise ValueError("Consolidation context changed; generate a fresh proposal")
    if not target.actor.startswith("hermes:") or has_human_review(ledger, target):
        return []
    if command.proposal.note is None:
        return []
    validate_note_revision(
        command.proposal,
        target,
        [ledger.require(reference, batch_id) for reference in command.context],
    )
    return [
        notes.save(
            ledger,
            batch_id,
            command.proposal.note,
            "hermes:gpt-5.6-luna:consolidate-v1",
            command.target,
        )
    ]


def consolidate_note(
    application: Knowledge,
    batch_id: str,
    target: Record,
    records: list[Record],
    run_directory: Path,
) -> None:
    """Record one proposed diff and atomically revise only unreviewed model prose."""
    saved = run_directory / f"note-{target.entity_id}-{target.revision}.json"
    if saved.exists():
        previous = ConsolidateNote.model_validate_json(saved.read_text())
        receipt_id = (
            "consolidate:" + hashlib.sha256(previous.model_dump_json().encode()).hexdigest()
        )
        with application.database.transaction() as ledger:
            if ledger.get_receipt(receipt_id):
                return
    command = propose_note_revision(target, records, run_directory)
    request_id = "consolidate:" + hashlib.sha256(command.model_dump_json().encode()).hexdigest()
    write_note_proposal(application, batch_id, target, command, request_id, run_directory)


def propose_note_revision(
    target: Record, records: list[Record], run_directory: Path
) -> ConsolidateNote:
    """Generate a validated proposal with the exact context revisions supplied to Luna."""
    supplied = note_context(target, records)
    packet = note_packet(target, supplied, records)
    prompt = Path(__file__).with_name("prompts") / "consolidate.md"
    proposal = generate(
        prompt.read_text(),
        packet,
        NoteRevision,
        run_directory / "proposals",
        lambda result: validate_note_revision(result, target, supplied),
    )
    return ConsolidateNote(
        target=target.reference(),
        proposal=proposal,
        context=[record.reference() for record in supplied],
    )


def note_context(target: Record, records: list[Record]) -> list[Record]:
    """Select all claim assessments and complete evidence for the target's linked claims."""
    note = target.payload
    assert isinstance(note, Note)
    referenced = {reference.entity_id for reference in note.references}
    linked_claims = set(referenced)
    for record in records:
        if record.entity_id in referenced and isinstance(record.payload, (Evidence, Assessment)):
            linked_claims.add(record.payload.claim.entity_id)
    cited = set(re.findall(r"\[([0-9a-f-]{36})@\d+\]", note.body))
    selected = []
    for record in records:
        payload = record.payload
        if record.kind in {"claim", "assessment"}:
            selected.append(record)
        elif isinstance(payload, Evidence) and (
            str(record.entity_id) in cited
            or (note.kind != "wiki" and payload.claim.entity_id in linked_claims)
        ):
            selected.append(record)
        elif isinstance(payload, Note) and record.entity_id != target.entity_id:
            if payload.kind in {"permanent", "wiki"}:
                selected.append(record)
    return selected


def note_packet(target: Record, supplied: list[Record], records: list[Record]) -> str:
    """Expose selected evidence and explicit omissions without truncating scientific records."""
    related_notes = [
        {
            "reference": record.reference().model_dump(mode="json"),
            "title": record.payload.title,
            "summary": record.payload.body[:500],
        }
        for record in supplied
        if isinstance(record.payload, Note)
        and record.entity_id != target.entity_id
        and record.payload.kind in {"permanent", "wiki"}
    ]
    packet = json.dumps(
        {
            "target": target.model_dump(mode="json"),
            "knowledge": knowledge_packet(supplied),
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


def write_note_proposal(
    application: Knowledge,
    batch_id: str,
    target: Record,
    command: ConsolidateNote,
    request_id: str,
    run_directory: Path,
) -> None:
    """Persist an inspectable proposal before accepting its database transaction."""
    previous = target.payload
    assert isinstance(previous, Note)
    diff = note_diff(previous, command.proposal.note, command.target)
    proposal_path = run_directory / f"note-{target.entity_id}-{target.revision}.json"
    proposal_path.write_text(command.model_dump_json(indent=2))
    record_event(
        run_directory,
        "note_proposal",
        target=command.target.model_dump(mode="json"),
        action=command.proposal.action,
        rationale=command.proposal.rationale,
        diff=diff,
    )
    references = application.database.command(
        request_id,
        batch_id,
        "consolidate",
        command,
        "hermes:gpt-5.6-luna:consolidate-v1",
        lambda ledger: apply_note_revision(ledger, batch_id, command),
    )
    record_event(
        run_directory,
        "note_result",
        target=str(target.entity_id),
        result="revised" if references else "kept_or_human_review_required",
    )


def note_diff(previous: Note, replacement: Note | None, target: Reference) -> str:
    """Show title, body and citation changes, including proposals that change only a title."""
    if replacement is None:
        return ""
    return "".join(
        difflib.unified_diff(
            note_review_text(previous).splitlines(keepends=True),
            note_review_text(replacement).splitlines(keepends=True),
            fromfile=f"{target.entity_id}@{target.revision}",
            tofile="proposal",
        )
    )


def note_review_text(note: Note) -> str:
    """Render the complete editable note as readable Markdown for a review diff."""
    references = "\n".join(
        f"- {reference.entity_id}@{reference.revision}" for reference in note.references
    )
    return f"# {note.title}\n\n{note.body}\n\nReferences:\n{references}\n"


def reassess_claim(
    application: Knowledge, batch_id: str, claim: Record, run_directory: Path
) -> None:
    """Update stale model assessments from the complete current evidence set."""
    with application.database.transaction() as ledger:
        relations = records_for_claim(ledger.list(batch_id, "evidence"), claim.reference())
        assessments = [
            record
            for record in ledger.list(batch_id, "assessment")
            if isinstance(record.payload, Assessment) and record.payload.claim == claim.reference()
        ]
        existing = max(assessments, key=lambda record: record.created_at) if assessments else None
        if existing and (
            review.is_current(ledger, existing) or not existing.actor.startswith("hermes:")
        ):
            return
    packet = json.dumps(
        {
            "claim": claim.model_dump(mode="json"),
            "evidence": [record.model_dump(mode="json") for record in relations],
            "coverage": "Convenience-selected supplied texts; no systematic literature search.",
        }
    )
    prompt = Path(__file__).with_name("prompts") / "assess.md"
    assessment = generate(
        prompt.read_text(),
        packet,
        Assessment,
        run_directory / "proposals",
        lambda result: validate_assessment(result, claim.reference(), relations),
    )
    command = AssessmentCommand(
        assessment=assessment, expected=existing.reference() if existing else None
    )
    identity = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
    application.assess(
        f"reassess:{identity}", batch_id, command, "hermes:gpt-5.6-luna:consolidate-assess-v1"
    )
    record_event(
        run_directory,
        "assessment",
        claim=str(claim.entity_id),
        evidence_count=len(relations),
        balance=assessment.balance,
    )


def validate_assessment(assessment: Assessment, claim: Reference, relations: list[Record]) -> None:
    """Reject changed claims or incomplete evidence before accepting model output."""
    expected = [record.reference() for record in relations]
    if assessment.claim != claim or sorted(map(str, assessment.evidence)) != sorted(
        map(str, expected)
    ):
        raise ValueError("Assessment must retain the supplied claim and complete evidence set")
    labels = [
        record.payload.relation for record in relations if isinstance(record.payload, Evidence)
    ]
    review.validate_balance(assessment, set(labels))


def consolidate(application: Knowledge, batch_id: str, run_directory: Path) -> None:
    """Reassess evidence and improve existing Zettel and wiki entries without creating notes."""
    record_event(run_directory, "consolidation_started", batch=batch_id)
    with application.database.transaction() as ledger:
        claims = ledger.list(batch_id, "claim")
        targets = consolidation_targets(ledger, batch_id, run_directory)
    for claim in claims:
        reassess_claim(application, batch_id, claim, run_directory)
    for target in targets:
        with application.database.transaction() as ledger:
            records = ledger.list(batch_id)
        consolidate_note(application, batch_id, target, records, run_directory)
    record_event(run_directory, "consolidation_completed", notes_considered=len(targets))


def has_human_review(ledger: Ledger, target: Record) -> bool:
    """Preserve human approval even when later evidence makes that review stale."""
    return any(
        isinstance(record.payload, Review)
        and record.payload.target.entity_id == target.entity_id
        and record.payload.verdict == "reviewed"
        for record in ledger.list(target.batch_id, "review")
    )


def consolidation_targets(ledger: Ledger, batch_id: str, run_directory: Path) -> list[Record]:
    """Pin the initial target set so a resumed run cannot repeatedly rewrite completed notes."""
    manifest = run_directory / "targets.json"
    if not manifest.exists():
        targets = [
            record.reference().model_dump(mode="json")
            for record in ledger.list(batch_id, "note")
            if isinstance(record.payload, Note) and record.payload.kind in {"permanent", "wiki"}
        ]
        manifest.write_text(json.dumps(targets))
    references = [Reference.model_validate(entry) for entry in json.loads(manifest.read_text())]
    return [ledger.require(reference, batch_id, "note") for reference in references]
