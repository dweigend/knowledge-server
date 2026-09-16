"""Improve existing notes through citation-preserving revision proposals.

The workflow validates protected content and exact citations, records diffs, and
reassesses affected claims after accepted changes.
"""

import difflib
import hashlib
import json
from pathlib import Path

from pydantic import TypeAdapter

from knowledge.knowledge_base import (
    claim_evidence_records,
    knowledge_service,
    note_records,
    review_records,
)
from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.model_integration import prompt_registry, structured_generation
from knowledge.revision_store import postgresql_revision_store
from knowledge.runtime_support import workflow_event_log
from knowledge.source_workflows import note_revision_proposals

CONSOLIDATION_ACTOR = "hermes:consolidate-v1"
REFERENCES = TypeAdapter(list[models.Reference])


def apply_note_revision(
    ledger: postgresql_revision_store.Ledger,
    batch_id: str,
    command: note_revision_proposals.ConsolidateNote,
) -> list[models.Reference]:
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
    note_revision_proposals.validate_note_revision(
        command.proposal,
        target,
        [ledger.require(reference, batch_id) for reference in command.context],
    )
    return [
        note_records.save(
            ledger,
            batch_id,
            command.proposal.note,
            CONSOLIDATION_ACTOR,
            command.target,
        )
    ]


def consolidate_note(
    application: knowledge_service.Knowledge,
    batch_id: str,
    target: models.Record,
    records: list[models.Record],
    run_directory: Path,
) -> None:
    """Record one proposed diff and atomically revise only unreviewed model prose."""
    saved = run_directory / f"note-{target.entity_id}-{target.revision}.json"
    if saved.exists():
        previous = note_revision_proposals.ConsolidateNote.model_validate_json(saved.read_text())
        receipt_id = (
            "consolidate:" + hashlib.sha256(previous.model_dump_json().encode()).hexdigest()
        )
        with application.database.transaction() as ledger:
            if ledger.get_receipt(receipt_id):
                return
    command = note_revision_proposals.propose_note_revision(target, records, run_directory)
    request_id = "consolidate:" + hashlib.sha256(command.model_dump_json().encode()).hexdigest()
    write_note_proposal(application, batch_id, target, command, request_id, run_directory)


def write_note_proposal(
    application: knowledge_service.Knowledge,
    batch_id: str,
    target: models.Record,
    command: note_revision_proposals.ConsolidateNote,
    request_id: str,
    run_directory: Path,
) -> None:
    """Persist an inspectable proposal before accepting its database transaction."""
    previous = target.payload
    assert isinstance(previous, models.Note)
    diff = note_diff(previous, command.proposal.note, command.target)
    proposal_path = run_directory / f"note-{target.entity_id}-{target.revision}.json"
    proposal_path.write_text(command.model_dump_json(indent=2))
    workflow_event_log.record_event(
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
        CONSOLIDATION_ACTOR,
        lambda ledger: apply_note_revision(ledger, batch_id, command),
    )
    workflow_event_log.record_event(
        run_directory,
        "note_result",
        target=str(target.entity_id),
        result="revised" if references else "kept_or_human_review_required",
    )


def note_diff(
    previous: models.Note, replacement: models.Note | None, target: models.Reference
) -> str:
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


def note_review_text(note: models.Note) -> str:
    """Render the complete editable note as readable Markdown for a review diff."""
    references = "\n".join(
        f"- {reference.entity_id}@{reference.revision}" for reference in note.references
    )
    return f"# {note.title}\n\n{note.body}\n\nReferences:\n{references}\n"


def reassess_claim(
    application: knowledge_service.Knowledge,
    batch_id: str,
    claim: models.Record,
    run_directory: Path,
) -> None:
    """Update stale model assessments from the complete current evidence set."""
    with application.database.transaction() as ledger:
        relations = claim_evidence_records.records_for_claim(
            ledger.list(batch_id, "evidence"), claim.reference()
        )
        assessments = [
            record
            for record in ledger.list(batch_id, "assessment")
            if isinstance(record.payload, models.Assessment)
            and record.payload.claim == claim.reference()
        ]
        existing = max(assessments, key=lambda record: record.created_at) if assessments else None
        if existing and (
            review_records.is_current(ledger, existing) or not existing.actor.startswith("hermes:")
        ):
            return
    packet = json.dumps(
        {
            "claim": claim.model_dump(mode="json"),
            "evidence": [record.model_dump(mode="json") for record in relations],
            "coverage": "Convenience-selected supplied texts; no systematic literature search.",
        }
    )
    prompt = prompt_registry.load_prompt("assess")
    assessment = structured_generation.generate(
        prompt,
        packet,
        models.Assessment,
        run_directory / "proposals",
        lambda result: validate_assessment(result, claim.reference(), relations),
    )
    command = knowledge_service.AssessmentCommand(
        assessment=assessment, expected=existing.reference() if existing else None
    )
    identity = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
    application.assess(f"reassess:{identity}", batch_id, command, "hermes:consolidate-assess-v1")
    workflow_event_log.record_event(
        run_directory,
        "assessment",
        claim=str(claim.entity_id),
        evidence_count=len(relations),
        balance=assessment.balance,
    )


def validate_assessment(
    assessment: models.Assessment,
    claim: models.Reference,
    relations: list[models.Record],
) -> None:
    """Reject changed claims or incomplete evidence before accepting model output."""
    expected = [record.reference() for record in relations]
    if assessment.claim != claim or sorted(map(str, assessment.evidence)) != sorted(
        map(str, expected)
    ):
        raise ValueError("Assessment must retain the supplied claim and complete evidence set")
    labels = [
        record.payload.relation
        for record in relations
        if isinstance(record.payload, models.Evidence)
    ]
    review_records.validate_balance(assessment, set(labels))


def consolidate(
    application: knowledge_service.Knowledge, batch_id: str, run_directory: Path
) -> None:
    """Reassess evidence and improve existing Zettel and wiki entries without creating notes."""
    workflow_event_log.record_event(run_directory, "consolidation_started", batch=batch_id)
    with application.database.transaction() as ledger:
        claims = ledger.list(batch_id, "claim")
        targets = consolidation_targets(ledger, batch_id, run_directory)
    for claim in claims:
        reassess_claim(application, batch_id, claim, run_directory)
    for target in targets:
        with application.database.transaction() as ledger:
            records = ledger.list(batch_id)
        consolidate_note(application, batch_id, target, records, run_directory)
    workflow_event_log.record_event(
        run_directory, "consolidation_completed", notes_considered=len(targets)
    )


def has_human_review(ledger: postgresql_revision_store.Ledger, target: models.Record) -> bool:
    """Preserve human approval even when later evidence makes that review stale."""
    return any(
        isinstance(record.payload, models.Review)
        and record.payload.target.entity_id == target.entity_id
        and record.payload.verdict == "reviewed"
        for record in ledger.list(target.batch_id, "review")
    )


def consolidation_targets(
    ledger: postgresql_revision_store.Ledger, batch_id: str, run_directory: Path
) -> list[models.Record]:
    """Pin the initial target set so a resumed run cannot repeatedly rewrite completed notes."""
    manifest = run_directory / "targets.json"
    if manifest.exists():
        references = REFERENCES.validate_json(manifest.read_bytes())
    else:
        references = [
            record.reference()
            for record in ledger.list(batch_id, "note")
            if isinstance(record.payload, models.Note)
            and record.payload.kind in {"permanent", "wiki"}
        ]
        manifest.write_bytes(REFERENCES.dump_json(references))
    return [ledger.require(reference, batch_id, "note") for reference in references]
