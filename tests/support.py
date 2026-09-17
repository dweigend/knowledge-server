"""Seed historical fixtures through real domain rules without a production legacy importer."""

import knowledge.knowledge_base.claim_evidence_records as evidence
import knowledge.knowledge_base.note_records as notes
from knowledge.knowledge_base.knowledge_service import Knowledge
from knowledge.knowledge_domain.knowledge_record_models import (
    Claim,
    Contract,
    Evidence,
    ExtractedClaim,
    LegacySource,
    Note,
    Reference,
)
from knowledge.revision_store.postgresql_revision_store import Ledger


class SeedArticle(Contract):
    source: LegacySource
    claim: ExtractedClaim
    zettel_body: str = "Performance is not retention."


def seed_article(application: Knowledge, request_id: str, article: SeedArticle) -> list[Reference]:
    return application.database.command(
        request_id,
        "pilot",
        "seed_historical_article",
        article,
        "hermes:fixture",
        lambda ledger: write_seed_records(ledger, article),
    )


def write_seed_records(ledger: Ledger, article: SeedArticle) -> list[Reference]:
    actor = "hermes:fixture"
    source = ledger.append("pilot", "source", article.source, actor)
    claim_fields = {"proposition", "scope", "qualifications"}
    claim = evidence.propose_claim(
        ledger, "pilot", Claim.model_validate(article.claim.model_dump(include=claim_fields)), actor
    )
    relation = evidence.link(
        ledger,
        "pilot",
        Evidence(claim=claim, source=source, **article.claim.model_dump(exclude=claim_fields)),
        actor,
    )
    source_note = notes.save(
        ledger,
        "pilot",
        Note(
            kind="source",
            title=article.source.bibliography.title,
            body="Summary",
            references=[source],
        ),
        actor,
    )
    zettel = notes.save(
        ledger,
        "pilot",
        Note(
            kind="permanent",
            title="Performance",
            body=article.zettel_body,
            references=[source, claim, relation],
        ),
        actor,
    )
    return [source, claim, relation, source_note, zettel]
