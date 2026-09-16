from typing import NamedTuple
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from support import seed_article

import knowledge.knowledge_base.review_records as review
from knowledge.knowledge_base.knowledge_service import (
    AssessmentCommand,
    EditNote,
    ReviewCommand,
)
from knowledge.knowledge_domain.application_errors import Conflict
from knowledge.knowledge_domain.knowledge_record_models import Assessment, Evidence, Note, Reference
from knowledge.runtime_support.environment_settings import Settings
from knowledge.web_interface.fastapi_app import create_app


class ArticleReferences(NamedTuple):
    source: Reference
    claim: Reference
    evidence: Reference
    source_note: Reference
    zettel: Reference


def import_article(application, article) -> ArticleReferences:
    return ArticleReferences(*seed_article(application, "first", article))


def assess(application, references: ArticleReferences):
    return application.assess(
        "assess",
        "pilot",
        AssessmentCommand(
            assessment=Assessment(
                claim=references.claim,
                evidence=[references.evidence],
                balance="mostly_supported",
                confidence="low",
                rationale="Single direct result",
                coverage="One source",
                limitations="Unknown overlap",
            )
        ),
        "hermes:fixture",
    )[0]


def test_atomic_idempotency_and_payload_conflict(application, article):
    first = import_article(application, article)
    assert import_article(application, article) == first
    changed = article.model_copy(update={"zettel_body": "different"})
    with pytest.raises(Conflict):
        seed_article(application, "first", changed)
    with application.database.transaction() as ledger:
        assert len(ledger.list("pilot")) == 5


def test_fabricated_quote_rolls_back_everything(application, article):
    article.claim.quote = "Invented result"
    with pytest.raises(ValueError, match="exact substring"):
        import_article(application, article)
    with application.database.transaction() as ledger:
        assert ledger.list("pilot") == []
        assert ledger.connection.execute("SELECT count(*) AS n FROM requests").fetchone()["n"] == 0


def test_human_review_invalidated_by_new_evidence(application, article):
    references = import_article(application, article)
    assessment_ref = assess(application, references)
    application.decide(
        "review",
        "pilot",
        ReviewCommand(
            target=assessment_ref,
            verdict="reviewed",
            comment="Checked wording and source",
        ),
        "human:local",
    )
    with application.database.transaction() as ledger:
        assert review.status(ledger, ledger.get(assessment_ref.entity_id)) == "reviewed"
    application.link_evidence(
        "new-evidence",
        "pilot",
        Evidence(
            claim=references.claim,
            source=references.source,
            page=1,
            quote="No retention was measured.",
            relation="qualifies",
            rationale="Outcome boundary",
            directness="direct",
            methodology="Same study",
            limitations="Not independent",
        ),
        "hermes:fixture",
    )
    with application.database.transaction() as ledger:
        assert review.status(ledger, ledger.get(assessment_ref.entity_id)) == "needs_review"
        assert len(ledger.list("pilot", "review")) == 1
    with pytest.raises(Conflict):
        application.decide(
            "stale-review",
            "pilot",
            ReviewCommand(
                target=assessment_ref,
                verdict="reviewed",
                comment="Stale",
            ),
            "human:local",
        )


def test_assessment_cannot_hide_relations_or_invent_mixed_balance(application, article):
    references = import_article(application, article)
    proposal = Assessment(
        claim=references.claim,
        evidence=[references.evidence],
        balance="mixed",
        confidence="low",
        rationale="Not valid",
        coverage="One",
        limitations="One",
    )
    with pytest.raises(ValueError, match="balance does not match"):
        application.assess("mixed", "pilot", AssessmentCommand(assessment=proposal), "hermes:test")
    proposal.balance = "open"
    proposal.evidence = []
    with pytest.raises(ValueError, match="every current"):
        application.assess(
            "missing", "pilot", AssessmentCommand(assessment=proposal), "hermes:test"
        )


def test_revision_history_conflicts_and_database_immutability(application, article):
    references = import_article(application, article)
    with application.database.transaction() as ledger:
        original = ledger.get(references.zettel.entity_id)
    note = original.payload
    assert isinstance(note, Note)
    note = note.model_copy(update={"body": "Corrected wording"})
    command = EditNote(expected=original.reference(), note=note)
    updated = application.edit_note("edit", "pilot", command, "human:local")[0]
    assert updated.revision == 2
    with pytest.raises(Conflict):
        application.edit_note("stale", "pilot", command, "human:local")
    assert len(application.history(updated.entity_id)) == 2
    with (
        pytest.raises(psycopg.errors.RaiseException, match="append-only"),
        application.database.transaction() as ledger,
    ):
        ledger.connection.execute("DELETE FROM revisions")


def test_no_cross_batch_reference_or_agent_review(application, article):
    references = import_article(application, article)
    application.create_batch("other", "Other")
    with pytest.raises(ValueError, match="outside"):
        application.propose_note(
            "cross",
            "other",
            Note(
                kind="wiki",
                title="Title",
                body="Body",
                references=[references.source],
            ),
            "hermes:test",
        )
    with pytest.raises(ValueError, match="human"):
        application.decide(
            "agent-review",
            "pilot",
            ReviewCommand(
                target=references.claim,
                verdict="reviewed",
                comment="Cannot self-approve",
            ),
            "hermes:fixture",
        )


def test_html_escapes_source_and_blocks_csrf(application, article, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "knowledge.web_interface.fastapi_app.source_metadata",
        lambda records, database: {
            str(record.entity_id): {"title": "Fixture source"}
            for record in records
            if record.kind == "source"
        },
    )
    article.zettel_body = "<script>alert('unsafe')</script>"
    references = import_article(application, article)
    client = TestClient(
        create_app(Settings(database_url=application.database.database_url, archive_root=tmp_path))
    )
    page = client.get(f"/records/{references.zettel.entity_id}")
    assert page.status_code == 200
    assert "<script>alert" not in page.text
    assert "&lt;script&gt;" in page.text
    rejected_review = client.post(
        f"/records/{references.zettel.entity_id}/review",
        data={
            "revision": "1",
            "verdict": "reviewed",
            "comment": "Test",
            "csrf": "wrong",
            "request_id": str(uuid4()),
        },
    )
    assert rejected_review.status_code == 403
    assert client.get("/", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/api/requests/first").status_code == 200
    assert client.get("/api/requests/unknown").status_code == 404


def test_claim_review_and_note_review_pin_evidence_set(application, article):
    references = import_article(application, article)
    for target in (references.claim, references.zettel):
        application.decide(
            f"review-{target.entity_id}",
            "pilot",
            ReviewCommand(
                target=target,
                verdict="reviewed",
                comment="Source checked",
            ),
            "human:local",
        )
    application.link_evidence(
        "new",
        "pilot",
        Evidence(
            claim=references.claim,
            source=references.source,
            page=1,
            quote="No retention was measured.",
            relation="qualifies",
            rationale="Boundary",
            directness="direct",
            methodology="Same study",
            limitations="Same data",
        ),
        "hermes:fixture",
    )
    with application.database.transaction() as ledger:
        assert review.status(ledger, ledger.get(references.claim.entity_id)) == "needs_review"
        assert review.status(ledger, ledger.get(references.zettel.entity_id)) == "needs_review"
