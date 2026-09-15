"""Seed historical fixtures through real domain rules without a production legacy importer."""

from knowledge import evidence, notes
from knowledge.application import Knowledge
from knowledge.contracts import (
    Claim,
    Contract,
    Evidence,
    ExtractedClaim,
    LegacySource,
    Note,
    Reference,
)
from knowledge.storage import Ledger


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
