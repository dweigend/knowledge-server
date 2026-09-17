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
from typing import Final, Literal

from knowledge.literature import literature_models
from knowledge.literature import (
    structured_paper_models as papers,
)
from knowledge.literature.bibliographic_identifiers import extracted_isbn, normalize_isbn
from knowledge.literature.crossref_client import lookup_crossref, normalize_doi

Lookup = Callable[
    [papers.PaperMetadata, float, Callable[[], bool]], list[literature_models.Candidate]
]
MIN_REQUEST_INTERVAL: Final[float] = 0.5
MAX_LOOKUP_SECONDS: Final[int] = 15


def normalized_words(text: str | None) -> str:
    """Normalize punctuation and Unicode for matching, never for stored quotations."""
    text = unicodedata.normalize("NFKD", text or "").casefold()
    unaccented = "".join(c for c in text if not unicodedata.combining(c))
    words = [match.group() for match in re.finditer(r"[^\W_]+", unaccented)]
    return " ".join(words)


def title_matches(original: papers.PaperMetadata, candidate: literature_models.Candidate) -> bool:
    """Require strong title agreement even when an extracted DOI exists."""
    left, right = normalized_words(original.title), normalized_words(candidate.metadata.title)
    if not left or not right:
        if candidate.method in {"doi", "isbn"}:
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


def candidate_rejection_reasons(
    original: papers.PaperMetadata, candidate: literature_models.Candidate
) -> list[str]:
    """Explain every deterministic identity check that rejected a candidate."""
    reasons = []
    if not title_matches(original, candidate):
        reasons.append("Title evidence does not agree closely enough.")
    if _chapter_conflicts_with_book(original, candidate):
        reasons.append("A cited chapter cannot be confirmed as its containing book.")
    if candidate.method == "doi":
        reasons.extend(_doi_rejection_reasons(original, candidate))
    elif candidate.method == "isbn":
        reasons.extend(_isbn_rejection_reasons(original, candidate))
    else:
        reasons.extend(_bibliographic_rejection_reasons(original, candidate))
    return reasons


def _chapter_conflicts_with_book(
    original: papers.PaperMetadata, candidate: literature_models.Candidate
) -> bool:
    return (
        isinstance(original, papers.PaperReference)
        and bool(re.search(r"\b[Ii]n\s*:", original.raw or ""))
        and candidate.metadata.work_type in {"book", "monograph", "edited-book"}
    )


def _doi_rejection_reasons(
    original: papers.PaperMetadata, candidate: literature_models.Candidate
) -> list[str]:
    doi = normalize_doi(original.doi)
    if doi is None:
        return ["The extracted source has no DOI to corroborate this DOI candidate."]
    if doi != normalize_doi(candidate.metadata.doi):
        return ["The candidate DOI differs from the extracted DOI."]
    return []


def _isbn_rejection_reasons(
    original: papers.PaperMetadata, candidate: literature_models.Candidate
) -> list[str]:
    isbn = extracted_isbn(original)
    candidate_isbns = {normalize_isbn(entry) for entry in candidate.metadata.isbn}
    if isbn is None:
        return ["The extracted source has no valid ISBN to corroborate this edition."]
    if isbn not in candidate_isbns:
        return ["The candidate ISBN differs from the extracted ISBN."]
    return []


def _bibliographic_rejection_reasons(
    original: papers.PaperMetadata, candidate: literature_models.Candidate
) -> list[str]:
    reasons = []
    if not original.year:
        reasons.append("The extracted source has no publication year for corroboration.")
    elif original.year != candidate.metadata.year:
        reasons.append("The candidate publication year differs from the extracted year.")
    if not original.authors:
        reasons.append("The extracted source has no author for corroboration.")
    else:
        surnames = {author_surname(author) for author in candidate.metadata.authors}
        first_author = author_surname(original.authors[0])
        if not first_author or first_author not in surnames:
            reasons.append("The candidate authors do not include the extracted first author.")
    return reasons


def candidate_matches(
    original: papers.PaperMetadata, candidate: literature_models.Candidate
) -> bool:
    """Accept exact DOI agreement or a corroborated bibliographic identity."""
    return not candidate_rejection_reasons(original, candidate)


def author_surname(author: str) -> str:
    """Recognize catalog commas and trailing initials without matching unrelated given names."""
    words = normalized_words(author.split(",", 1)[0]).split()
    if not words:
        return ""
    if "," in author or len(words[-1]) != 1:
        return words[-1]
    return next((word for word in reversed(words) if len(word) > 1), "")


def resolve_reference(
    reference: papers.PaperReference, candidates: list[literature_models.Candidate]
) -> literature_models.Resolution:
    """Keep ambiguity and rejected candidates explicit instead of guessing an identity."""
    matches: dict[str, literature_models.Candidate] = {}
    rejections: list[literature_models.CandidateRejection] = []
    for candidate in candidates:
        reasons = candidate_rejection_reasons(reference, candidate)
        if reasons:
            rejections.append(
                literature_models.CandidateRejection(
                    provider=candidate.provider,
                    provider_id=candidate.provider_id,
                    reasons=reasons,
                )
            )
            continue
        identity = candidate_identity(candidate)
        previous = matches.get(identity)
        if previous is not None and metadata_completeness(candidate) <= metadata_completeness(
            previous
        ):
            continue
        matches[identity] = candidate
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
        rejections=rejections,
    )


def candidate_identity(candidate: literature_models.Candidate) -> str:
    """Group matching DOI records across providers without conflating book editions."""
    doi = normalize_doi(candidate.metadata.doi)
    return f"doi:{doi}" if doi else candidate.provider + ":" + candidate.provider_id.lower()


def metadata_completeness(candidate: literature_models.Candidate) -> int:
    """Prefer the richest corroborated response for the same persistent identity."""
    return sum(bool(field) for field in candidate.metadata.model_dump().values())


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
