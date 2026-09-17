"""Define result contracts used only by manual experiments.

These models preserve source provenance and reviewable proposals without
accepting any result into canonical knowledge.
"""

from pydantic import Field

from knowledge.knowledge_domain import knowledge_record_models
from knowledge.source_workflows import (
    article_claim_extraction,
    claim_matching,
    information_block_extraction,
    note_revision_proposals,
)


class GroundedClaim(knowledge_record_models.Contract):
    """Associate an unchanged claim proposal with exact source-block provenance."""

    proposal: knowledge_record_models.ExtractedClaim
    block_indexes: list[int] = Field(min_length=1)
    sources: list[information_block_extraction.SourceSpan] = Field(min_length=1)


class ClaimFormulation(knowledge_record_models.Contract):
    """Retain import metadata and proposed claims without writing to a ledger."""

    extractions: list[article_claim_extraction.ArticleExtraction]
    claims: list[GroundedClaim]


class ClaimChange(knowledge_record_models.Contract):
    """Keep an evidence-relation proposal with its extracted source passage."""

    claim: GroundedClaim
    decision: claim_matching.ClaimDecision


class NoteChange(knowledge_record_models.Contract):
    """Present a validated note proposal together with its exact text diff."""

    command: note_revision_proposals.ConsolidateNote
    diff: str


class KnowledgeChanges(knowledge_record_models.Contract):
    """Collect reviewable proposals without accepting or persisting records."""

    claims: list[ClaimChange]
    notes: list[NoteChange]
    warnings: list[str]
