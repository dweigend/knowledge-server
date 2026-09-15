"""Retrieve pinned knowledge and record explicit selection before proposing changes."""

import json
import re
from collections.abc import Callable
from pathlib import Path

from pydantic import Field

from knowledge.contracts import Contract, Record, Reference
from knowledge.generation import ModelConfiguration, generate

MAX_RETRIEVAL_RECORDS = 40
MAX_KNOWLEDGE_CHARACTERS = 120000


class RetrievalHit(Contract):
    """Keep a whole immutable candidate and the lexical terms that retrieved it."""

    record: Record
    matched_terms: list[str]
    score: int = Field(ge=1)


class KnowledgeRetrieval(Contract):
    """Describe deterministic lexical retrieval over the explicitly supplied knowledge."""

    query: str
    method: str = "lexical-token-overlap-v1"
    corpus_size: int = Field(ge=0)
    hits: list[RetrievalHit]


class EntrySelection(Contract):
    """Explain inclusion or exclusion of one retrieved immutable record."""

    reference: Reference
    selected: bool
    rationale: str = Field(min_length=1)


class KnowledgeSelection(Contract):
    """Account for every retrieved candidate before any proposed action."""

    entries: list[EntrySelection]


def retrieve_knowledge(query: str, records: list[Record], limit: int = 20) -> KnowledgeRetrieval:
    """Rank lexical matches without silently reading any external knowledge state."""
    if not query.strip() or not 1 <= limit <= MAX_RETRIEVAL_RECORDS:
        raise ValueError("Retrieval requires a query and a limit between 1 and 40")
    terms = set(re.findall(r"\w{3,}", query.casefold()))
    hits = []
    for record in records:
        if record.kind not in {"claim", "source", "note"}:
            continue
        content = record.payload.model_dump_json().casefold()
        matched = sorted(terms.intersection(re.findall(r"\w{3,}", content)))
        if matched:
            hits.append(RetrievalHit(record=record, matched_terms=matched, score=len(matched)))
    hits.sort(key=lambda hit: (-hit.score, str(hit.record.entity_id), hit.record.revision))
    return KnowledgeRetrieval(query=query, corpus_size=len(records), hits=hits[:limit])


def validate_selection(selection: KnowledgeSelection, retrieval: KnowledgeRetrieval) -> None:
    """Reject invented revisions, duplicates and unaccounted-for candidates."""
    references = [entry.reference for entry in selection.entries]
    expected = [hit.record.reference() for hit in retrieval.hits]
    if len(references) != len(expected) or any(references.count(ref) != 1 for ref in expected):
        raise ValueError("Selection must account for each retrieved revision exactly once")


def select_knowledge(
    retrieval: KnowledgeRetrieval,
    question: str,
    instructions: str,
    output_directory: Path,
    configuration: ModelConfiguration,
    cancelled: Callable[[], bool],
) -> KnowledgeSelection:
    """Request explicit choices through the shared model and reference validators."""
    if not retrieval.hits:
        return KnowledgeSelection(entries=[])
    packet = json.dumps({"question": question, "retrieval": retrieval.model_dump(mode="json")})
    if len(packet) > MAX_KNOWLEDGE_CHARACTERS:
        raise ValueError("Selection exceeds its 120000-character context budget")
    return generate(
        instructions,
        packet,
        KnowledgeSelection,
        output_directory,
        lambda result: validate_selection(result, retrieval),
        configuration=configuration,
        cancelled=cancelled,
    )
