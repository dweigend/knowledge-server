"""Coordinate typed knowledge commands across interfaces and workflows.

The application service delegates atomic writes to the owning domain operations
through the revision ledger.
"""

from uuid import UUID

from knowledge.knowledge_base import (
    claim_evidence_records,
    note_records,
    review_records,
)
from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.revision_store import postgresql_revision_store as store


class EditNote(models.Contract):
    """Replace a note only when its expected revision is still current."""

    expected: models.Reference
    note: models.Note


class ReviewCommand(models.Contract):
    """Record a human verdict against one exact record revision."""

    target: models.Reference
    verdict: str
    comment: str


class AssessmentCommand(models.Contract):
    """Propose or revise an assessment of a pinned claim and evidence set."""

    assessment: models.Assessment
    expected: models.Reference | None = None


class CompareEvidence(models.Contract):
    """Import selected cross-source evidence with its search coverage."""

    relations: list[models.Evidence]
    search_summary: str
    selected_pages: dict[str, list[int]]


class Knowledge:
    """Coordinate domain writes within one idempotent database transaction."""

    def __init__(self, database: store.Database):
        """Use the supplied database for all application commands."""
        self.database = database

    def create_batch(self, batch_id: str, title: str) -> None:
        """Create an import batch if its identifier is not already registered."""
        with self.database.transaction() as ledger:
            ledger.connection.execute(
                "INSERT INTO batches(batch_id, title) VALUES (%s, %s) "
                "ON CONFLICT (batch_id) DO NOTHING",
                (batch_id, title),
            )

    def edit_note(
        self,
        request_id: str,
        batch_id: str,
        command: EditNote,
        actor: str,
    ) -> list[models.Reference]:
        """Append a note revision and reject concurrent edits."""
        return self.database.command(
            request_id,
            batch_id,
            "edit_note",
            command,
            actor,
            lambda ledger: [
                note_records.save(ledger, batch_id, command.note, actor, command.expected)
            ],
        )

    def propose_note(
        self,
        request_id: str,
        batch_id: str,
        note: models.Note,
        actor: str,
    ) -> list[models.Reference]:
        """Save a new note with pinned references."""
        return self.database.command(
            request_id,
            batch_id,
            "propose_note",
            note,
            actor,
            lambda ledger: [note_records.save(ledger, batch_id, note, actor)],
        )

    def link_evidence(
        self,
        request_id: str,
        batch_id: str,
        relation: models.Evidence,
        actor: str,
    ) -> list[models.Reference]:
        """Save a source passage linked to one claim revision."""
        return self.database.command(
            request_id,
            batch_id,
            "link_evidence",
            relation,
            actor,
            lambda ledger: [claim_evidence_records.link(ledger, batch_id, relation, actor)],
        )

    def assess(
        self,
        request_id: str,
        batch_id: str,
        command: AssessmentCommand,
        actor: str,
    ) -> list[models.Reference]:
        """Save an assessment after checking its complete evidence set."""
        return self.database.command(
            request_id,
            batch_id,
            "assess",
            command,
            actor,
            lambda ledger: [
                review_records.propose_assessment(
                    ledger,
                    batch_id,
                    command.assessment,
                    actor,
                    command.expected,
                )
            ],
        )

    def import_comparison(
        self,
        request_id: str,
        batch_id: str,
        command: CompareEvidence,
        actor: str,
    ) -> list[models.Reference]:
        """Accept every comparison relation or roll back the entire request."""
        return self.database.command(
            request_id,
            batch_id,
            "compare",
            command,
            actor,
            lambda ledger: [
                claim_evidence_records.link(ledger, batch_id, relation, actor)
                for relation in command.relations
            ],
        )

    def decide(
        self,
        request_id: str,
        batch_id: str,
        command: ReviewCommand,
        actor: str,
    ) -> list[models.Reference]:
        """Save an attributed human verdict and pin its dependencies."""
        return self.database.command(
            request_id,
            batch_id,
            "review",
            command,
            actor,
            lambda ledger: [
                review_records.record_decision(
                    ledger,
                    batch_id,
                    command.target,
                    command.verdict,
                    command.comment,
                    actor,
                )
            ],
        )

    def history(self, entity_id: UUID) -> list[dict]:
        """Return all revisions in chronological revision order."""
        with self.database.transaction() as ledger:
            current = ledger.get(entity_id)
            return [
                ledger.get(entity_id, revision).model_dump(mode="json")
                for revision in range(1, current.revision + 1)
            ]
