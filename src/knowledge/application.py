"""Typed application commands shared by CLI, import and the disposable HTML adapter."""

from uuid import UUID

from knowledge import evidence, notes, review
from knowledge.contracts import (
    Assessment,
    Contract,
    Evidence,
    Note,
    Reference,
)
from knowledge.storage import Database


class EditNote(Contract):
    """Replace a note only when its expected revision is still current."""

    expected: Reference
    note: Note


class ReviewCommand(Contract):
    """Record a human verdict against one exact record revision."""

    target: Reference
    verdict: str
    comment: str


class AssessmentCommand(Contract):
    """Propose or revise an assessment of a pinned claim and evidence set."""

    assessment: Assessment
    expected: Reference | None = None


class CompareEvidence(Contract):
    """Import selected cross-source evidence with its search coverage."""

    relations: list[Evidence]
    search_summary: str
    selected_pages: dict[str, list[int]]


class Knowledge:
    """Coordinate domain writes within one idempotent database transaction."""

    def __init__(self, database: Database):
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
    ) -> list[Reference]:
        """Append a note revision and reject concurrent edits."""
        return self.database.command(
            request_id,
            batch_id,
            "edit_note",
            command,
            actor,
            lambda ledger: [notes.save(ledger, batch_id, command.note, actor, command.expected)],
        )

    def propose_note(
        self,
        request_id: str,
        batch_id: str,
        note: Note,
        actor: str,
    ) -> list[Reference]:
        """Save a new note with pinned references."""
        return self.database.command(
            request_id,
            batch_id,
            "propose_note",
            note,
            actor,
            lambda ledger: [notes.save(ledger, batch_id, note, actor)],
        )

    def link_evidence(
        self,
        request_id: str,
        batch_id: str,
        relation: Evidence,
        actor: str,
    ) -> list[Reference]:
        """Save a source passage linked to one claim revision."""
        return self.database.command(
            request_id,
            batch_id,
            "link_evidence",
            relation,
            actor,
            lambda ledger: [evidence.link(ledger, batch_id, relation, actor)],
        )

    def assess(
        self,
        request_id: str,
        batch_id: str,
        command: AssessmentCommand,
        actor: str,
    ) -> list[Reference]:
        """Save an assessment after checking its complete evidence set."""
        return self.database.command(
            request_id,
            batch_id,
            "assess",
            command,
            actor,
            lambda ledger: [
                review.propose_assessment(
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
    ) -> list[Reference]:
        """Accept every comparison relation or roll back the entire request."""
        return self.database.command(
            request_id,
            batch_id,
            "compare",
            command,
            actor,
            lambda ledger: [
                evidence.link(ledger, batch_id, relation, actor) for relation in command.relations
            ],
        )

    def decide(
        self,
        request_id: str,
        batch_id: str,
        command: ReviewCommand,
        actor: str,
    ) -> list[Reference]:
        """Save an attributed human verdict and pin its dependencies."""
        return self.database.command(
            request_id,
            batch_id,
            "review",
            command,
            actor,
            lambda ledger: [
                review.record_decision(
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
