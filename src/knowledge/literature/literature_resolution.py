"""Resolve literature identities conservatively and preserve citation provenance.

Provider candidates are accepted only when identifiers or normalized metadata
agree closely enough; ambiguity remains explicit.
"""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from difflib import SequenceMatcher
from time import monotonic, sleep
from typing import Literal

from knowledge.literature import literature_models
from knowledge.literature import (
    structured_paper_models as papers,
)
from knowledge.literature.crossref_client import lookup_crossref, normalize_doi

Lookup = Callable[
    [papers.PaperMetadata, float, Callable[[], bool]], list[literature_models.Candidate]
]
MIN_REQUEST_INTERVAL = 0.5
MAX_LOOKUP_SECONDS = 15


def normalized_words(text: str | None) -> str:
    """Normalize punctuation and Unicode for matching, never for stored quotations."""
    text = unicodedata.normalize("NFKD", text or "").casefold()
    return " ".join(
        re.findall(r"[^\W_]+", "".join(c for c in text if not unicodedata.combining(c)))
    )


def title_matches(original: papers.PaperMetadata, candidate: literature_models.Candidate) -> bool:
    """Require strong title agreement even when an extracted DOI exists."""
    left, right = normalized_words(original.title), normalized_words(candidate.metadata.title)
    if not left or not right:
        if candidate.method == "doi":
            return not left
        raw = normalized_words(original.raw) if isinstance(original, papers.PaperReference) else ""
        return len(right) >= 20 and len(right.split()) >= 3 and f" {right} " in f" {raw} "
    if left == right:
        return True
    if candidate.method == "doi" and left.startswith(right + " "):
        author_words = set(normalized_words(" ".join(candidate.metadata.authors)).split())
        if set(left[len(right) :].split()) <= author_words:
            return True
    return SequenceMatcher(None, left, right).ratio() >= 0.94


def candidate_matches(
    original: papers.PaperMetadata, candidate: literature_models.Candidate
) -> bool:
    """Accept exact DOI agreement or a corroborated bibliographic identity."""
    if not title_matches(original, candidate):
        return False
    if candidate.method == "doi":
        doi = normalize_doi(original.doi)
        return doi is not None and doi == normalize_doi(candidate.metadata.doi)
    if not original.year or original.year != candidate.metadata.year or not original.authors:
        return False
    # Compare surnames independent of initials, retaining conservative year agreement.
    surnames = {
        normalized_words(author).split()[-1]
        for author in candidate.metadata.authors
        if normalized_words(author)
    }
    first_author = normalized_words(original.authors[0]).split()
    return bool(first_author and first_author[-1] in surnames)


def resolve_reference(
    reference: papers.PaperReference, candidates: list[literature_models.Candidate]
) -> literature_models.Resolution:
    """Keep ambiguity and rejected candidates explicit instead of guessing an identity."""
    matches = {
        candidate.provider + ":" + candidate.provider_id.lower(): candidate
        for candidate in candidates
        if candidate_matches(reference, candidate)
    }
    status = "matched" if len(matches) == 1 else "ambiguous" if len(matches) > 1 else "unmatched"
    accepted = next(iter(matches.values())) if status == "matched" else None
    return literature_models.Resolution(
        status=status,
        provider=accepted.provider if accepted else None,
        method=accepted.method if accepted else None,
        checked_at=datetime.now(UTC).isoformat(),
        message={
            "matched": "Identity corroborated; missing fields still require review.",
            "ambiguous": "Multiple plausible works; manual review required.",
            "unmatched": "No sufficiently corroborated match; extracted metadata retained.",
        }[status],
        candidates=([accepted] + [c for c in candidates if c != accepted])
        if accepted
        else candidates,
    )


def lookup_resolution(
    reference: papers.PaperReference,
    deadline: float,
    cancelled: Callable[[], bool],
    lookup: Lookup,
) -> literature_models.Resolution:
    """Record lookup failures without discarding an otherwise usable extraction."""
    if cancelled():
        raise InterruptedError("Literature lookup cancelled")
    try:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Literature reconciliation time budget exhausted")
        return resolve_reference(
            reference, lookup(reference, min(remaining, MAX_LOOKUP_SECONDS), cancelled)
        )
    except InterruptedError:
        raise
    except (ValueError, OSError, KeyError, TypeError) as error:
        return literature_models.Resolution(
            status="error",
            checked_at=datetime.now(UTC).isoformat(),
            message=f"Literature lookup failed: {type(error).__name__}: {error}",
        )


def build_record(
    reference: papers.PaperReference,
    resolution: literature_models.Resolution,
    source_sha256: str,
    role: Literal["source", "reference"],
) -> literature_models.LiteratureRecord:
    """Assign stable identities only to accepted matches; retain original evidence."""
    metadata = literature_models.LiteratureMetadata(**reference.model_dump(exclude={"id", "raw"}))
    identity = f"sha256:{source_sha256}" + ("" if role == "source" else f":ref:{reference.id}")
    if resolution.status == "matched":
        accepted = resolution.candidates[0]
        metadata = accepted.metadata.model_copy(deep=True)
        doi = normalize_doi(metadata.doi)
        identity = f"doi:{doi}" if doi else f"{accepted.provider}:{accepted.provider_id}"
    return literature_models.LiteratureRecord(
        id=identity,
        role=role,
        source_sha256=source_sha256,
        metadata=metadata,
        extracted=[reference],
        reference_ids=[] if role == "source" else [reference.id],
        resolution=resolution,
        missing_fields=[
            field
            for field in ("title", "authors", "year", "venue", "doi")
            if not getattr(metadata, field)
        ],
    )


def enrich_paper(
    paper: papers.PaperDocument,
    source_sha256: str,
    *,
    timeout_seconds: float,
    cancelled: Callable[[], bool],
    lookup: Lookup | None = None,
) -> list[literature_models.LiteratureRecord]:
    """Reconcile a paper and bibliography, deduplicating only accepted stable identities."""
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 240:
        raise ValueError("Literature timeout must be between 0 and 240 seconds")
    deadline = monotonic() + timeout_seconds
    records: dict[str, literature_models.LiteratureRecord] = {}
    cache: dict[str, literature_models.Resolution] = {}
    provider_backoff: literature_models.Resolution | None = None
    references = [
        papers.PaperReference(id="__source__", **paper.metadata.model_dump()),
        *paper.references,
    ]
    reference_counts = Counter(reference.id for reference in paper.references)
    for index, reference in enumerate(references):
        key = reference.model_dump_json(exclude={"id"})
        if provider_backoff is not None:
            cache[key] = provider_backoff
        if key not in cache:
            if lookup is None and cache:
                wait_until = min(monotonic() + MIN_REQUEST_INTERVAL, deadline)
                while monotonic() < wait_until and not cancelled():
                    sleep(min(0.05, max(0, wait_until - monotonic())))
            cache[key] = lookup_resolution(
                reference, deadline, cancelled, lookup or lookup_crossref
            )
            if lookup is None and "HTTP 429" in cache[key].message:
                provider_backoff = cache[key].model_copy(
                    update={"message": "Crossref rate limited this run (HTTP 429); retry later."}
                )
        if cancelled():
            raise InterruptedError("Literature lookup cancelled")
        record = build_record(
            reference, cache[key], source_sha256, "source" if index == 0 else "reference"
        )
        if index and reference_counts[reference.id] > 1 and record.resolution.status != "matched":
            record.id += f":entry:{index}"
        collect_record(records, record)
    attach_occurrences(paper, source_sha256, records)
    return list(records.values())


def collect_record(
    records: dict[str, literature_models.LiteratureRecord],
    record: literature_models.LiteratureRecord,
) -> None:
    """Merge reference aliases only after the caller has assigned a safe identity."""
    if record.id not in records:
        records[record.id] = record
        return
    records[record.id].extracted.extend(record.extracted)
    records[record.id].reference_ids.extend(record.reference_ids)


def attach_occurrences(
    paper: papers.PaperDocument,
    source_sha256: str,
    records: dict[str, literature_models.LiteratureRecord],
) -> None:
    """Link every observed marker, retaining unknown targets as reviewable source-local stubs."""
    counts = Counter(reference.id for reference in paper.references)
    by_reference = {
        ref: record
        for record in records.values()
        for ref in record.reference_ids
        if counts[ref] == 1
    }
    for index, citation in enumerate(paper.citations):
        targets = citation.target_ids or [f"__unresolved_marker_{index}"]
        for target in targets:
            if target not in by_reference:
                reference = papers.PaperReference(id=target)
                stub = build_record(
                    reference,
                    resolve_reference(reference, []),
                    source_sha256,
                    "reference",
                )
                if counts[target] > 1:
                    stub.id += ":ambiguous"
                    stub.resolution.status = "ambiguous"
                    stub.resolution.message = (
                        "Duplicate bibliography identifier; citation target requires review."
                    )
                records[stub.id] = by_reference[target] = stub
            occurrence = literature_models.CitationOccurrence(
                citing_source_id=f"sha256:{source_sha256}",
                occurrence_index=index + 1,
                marker=citation.marker,
                context=citation.context,
                section=citation.section,
                coordinates=citation.coordinates,
                reference_ids=citation.target_ids,
            )
            record = by_reference[target]
            if occurrence not in record.occurrences:
                record.occurrences.append(occurrence)
