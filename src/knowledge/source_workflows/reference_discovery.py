"""Recover and identify references with bounded, evidence-driven fallback searches."""

import os
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from time import monotonic

from pydantic import BaseModel

from knowledge.literature import (
    crossref_client,
    dnb_client,
    google_books_client,
    literature_models,
    openalex_client,
    openlibrary_client,
    semantic_scholar_client,
    unpaywall_client,
)
from knowledge.literature import (
    literature_resolution as resolution,
)
from knowledge.literature import (
    reference_discovery_models as models,
)
from knowledge.literature import (
    structured_paper_models as papers,
)
from knowledge.literature.bibliographic_identifiers import extracted_isbn
from knowledge.model_integration import structured_generation
from knowledge.runtime_support.atomic_json_files import write_json_atomically
from knowledge.source_workflows import bibliography_recovery, reference_query_planning
from knowledge.source_workflows.bibliography_recovery_models import BibliographyAudit
from knowledge.source_workflows.reference_search import (
    ReferenceSearchSession,
    query_text,
    request_key,
)


class ReferenceDiscoveryResult(BaseModel):
    """Return recovered source evidence, literature records and the bounded search audit."""

    paper: papers.PaperDocument
    literature: list[literature_models.LiteratureRecord]
    report: models.DiscoveryReport
    bibliography: BibliographyAudit


def available_providers() -> dict[str, resolution.Lookup]:
    """Bind provider adapters without initiating network activity."""
    providers: dict[str, resolution.Lookup] = {
        "crossref": crossref_client.lookup_crossref,
        "dnb": dnb_client.lookup_dnb,
        "openalex": openalex_client.lookup_openalex,
        "openlibrary": openlibrary_client.lookup_openlibrary,
        "semantic_scholar": semantic_scholar_client.lookup_semantic_scholar,
        "google_books": google_books_client.lookup_google_books,
        "unpaywall": lookup_access,
    }
    if not os.environ.get("KNOWLEDGE_GOOGLE_BOOKS_API_KEY"):
        providers.pop("google_books")
    if not os.environ.get("KNOWLEDGE_UNPAYWALL_EMAIL"):
        providers.pop("unpaywall")
    return providers


def lookup_access(
    reference: papers.PaperMetadata, timeout_seconds: float, cancelled: Callable[[], bool]
) -> list[literature_models.Candidate]:
    """Adapt optional access discovery to the same bounded lookup cache."""
    if not reference.doi:
        return []
    location = unpaywall_client.lookup_unpaywall(reference.doi, timeout_seconds, cancelled)
    if location is None:
        return []
    return [
        literature_models.Candidate(
            provider="unpaywall",
            provider_id=reference.doi,
            method="doi",
            metadata=literature_models.LiteratureMetadata(
                doi=reference.doi,
                open_access_url=location.url,
                open_access_pdf_url=location.url_for_pdf,
            ),
        )
    ]


def search_trigger(
    record: literature_models.LiteratureRecord, settings: models.DiscoverySettings
) -> str:
    """Require fallback only for unresolved identities or explicitly required missing fields."""
    if record.resolution.status != "matched":
        return record.resolution.status
    missing = [field for field in settings.required_fields if not getattr(record.metadata, field)]
    return "Missing required fields: " + ", ".join(missing) if missing else ""


def evidence_reference(reference: papers.PaperReference) -> papers.PaperReference:
    """Restore a missing year only when the original citation supplies exactly one year."""
    updated = reference.model_copy(deep=True)
    years = set(re.findall(r"\b(?:1[5-9]|20)\d{2}\b", reference.raw or ""))
    if not updated.year and len(years) == 1:
        updated.year = years.pop()
    return updated


def reference_candidates(
    reference: papers.PaperReference, candidates: list[literature_models.Candidate]
) -> list[literature_models.Candidate]:
    """Exclude whole-book matches for citations that explicitly identify a contained chapter."""
    if not re.search(r"\b[Ii]n\s*:", reference.raw or ""):
        return candidates
    return [
        candidate
        for candidate in candidates
        if candidate.metadata.work_type not in {"book", "monograph", "edited-book"}
    ]


def resolved_record(
    reference: papers.PaperReference,
    candidates: list[literature_models.Candidate],
    source_sha256: str,
    refined: papers.PaperReference | None = None,
) -> literature_models.LiteratureRecord:
    """Keep identity decisions deterministic and retain the original extraction evidence."""
    corroborated = evidence_reference(refined or reference)
    result = resolution.resolve_reference(corroborated, reference_candidates(reference, candidates))
    role = "source" if reference.id == "__source__" else "reference"
    record = resolution.build_record(reference, result, source_sha256, role)
    if result.status == "matched":
        for field in ("title", "authors", "year", "venue"):
            if not getattr(record.metadata, field) and getattr(corroborated, field):
                setattr(record.metadata, field, getattr(corroborated, field))
        record.missing_fields = [
            field for field in record.missing_fields if not getattr(record.metadata, field)
        ]
    return record


def provider_order(
    reference: papers.PaperReference, settings: models.DiscoverySettings
) -> list[str]:
    """Prefer catalogs for book-like citations while preserving the configured provider set."""
    book_like = bool(
        re.search(
            r"\b(?:Verlag|Suhrkamp|Campus|ISBN|Hrsg|Stuttgart|München)\b", reference.raw or ""
        )
    )
    preferred = (
        ["dnb", "openlibrary", "google_books"] if book_like else ["openalex", "semantic_scholar"]
    )
    return list(
        dict.fromkeys(
            [name for name in preferred if name in settings.providers] + settings.providers
        )
    )


def search_reference(
    reference: papers.PaperReference,
    source_sha256: str,
    session: ReferenceSearchSession,
) -> tuple[literature_models.LiteratureRecord, list[literature_models.Candidate]]:
    """Stop provider searches as soon as identity and required metadata are sufficient."""
    trace = models.ReferenceSearch(reference_id=reference.id, trigger="Initial identification")
    session.report.searches.append(trace)
    if not has_search_evidence(reference):
        trace.trigger = "Insufficient bibliographic evidence; review required"
        return resolved_record(reference, [], source_sha256), []
    confirmed_path = confirmed_record_path(reference, source_sha256, session)
    if confirmed_path.exists():
        previous = literature_models.LiteratureRecord.model_validate_json(
            confirmed_path.read_text()
        )
        session.report.cache_hits += 1
        candidates = previous.resolution.candidates
        trace.queries.append(
            models.SearchQuery(
                provider=previous.resolution.provider or "cache",
                query=query_text(reference),
                status="success",
                cached=True,
                candidate_count=len(candidates),
                message="Reused confirmed identity.",
            )
        )
        if not search_trigger(previous, session.settings):
            trace.trigger = "Complete; fallback skipped"
            return previous, candidates
    else:
        candidates = session.search(initial_provider(reference, session.settings), reference, trace)
    record = resolved_record(reference, candidates, source_sha256)
    trace.trigger = search_trigger(record, session.settings) or "Complete; fallback skipped"
    if not search_trigger(record, session.settings):
        return record, candidates
    query = evidence_reference(reference)
    if query.doi:
        query.doi = None
        candidates.extend(session.search("crossref", query, trace))
        record = resolved_record(reference, candidates, source_sha256)
    for provider in provider_order(reference, session.settings):
        if not search_trigger(record, session.settings):
            break
        candidates.extend(session.search(provider, query, trace))
        record = resolved_record(reference, candidates, source_sha256)
    mark_lookup_failure(record, trace)
    return record, candidates


def confirmed_record_path(
    reference: papers.PaperReference, source_sha256: str, session: ReferenceSearchSession
) -> Path:
    """Retain confirmed identities across explicit retries of unresolved searches."""
    key = request_key("confirmed.v1", reference, 0)
    return session.cache_directory / "confirmed" / source_sha256 / f"{key}.json"


def has_search_evidence(reference: papers.PaperReference) -> bool:
    """Require a title, literal citation or DOI before spending lookup resources."""
    return bool(reference.title or reference.raw or crossref_client.normalize_doi(reference.doi))


def initial_provider(reference: papers.PaperReference, settings: models.DiscoverySettings) -> str:
    """Prefer a direct catalog ISBN lookup when the citation has no DOI."""
    if not crossref_client.normalize_doi(reference.doi) and extracted_isbn(reference):
        for provider in ("dnb", "openlibrary", "google_books"):
            if provider in settings.providers:
                return provider
    return "crossref"


def mark_lookup_failure(
    record: literature_models.LiteratureRecord, trace: models.ReferenceSearch
) -> None:
    """Distinguish unavailable providers and exhausted budgets from an ordinary no-match result."""
    failed = [query for query in trace.queries if query.status in {"error", "budget", "backoff"}]
    if record.resolution.status == "unmatched" and failed:
        record.resolution.message += " " + " ".join(
            dict.fromkeys(query.message for query in failed)
        )
        if all(query.status != "success" for query in trace.queries):
            record.resolution.status = "error"


def model_configuration(
    configuration: structured_generation.ModelConfiguration,
    settings: models.DiscoverySettings,
    deadline: float,
) -> structured_generation.ModelConfiguration:
    """Limit each optional model invocation to one attempt and the remaining wall-clock budget."""
    return structured_generation.ModelConfiguration.model_validate(
        {
            **configuration.model_dump(),
            "max_attempts": 1,
            "timeout_seconds": max(1, min(settings.model_timeout_seconds, deadline - monotonic())),
        }
    )


def refine_unresolved(
    references: list[papers.PaperReference],
    records: dict[str, literature_models.LiteratureRecord],
    candidates: dict[str, list[literature_models.Candidate]],
    session: ReferenceSearchSession,
    configuration: structured_generation.ModelConfiguration,
    source_sha256: str,
) -> None:
    """Use one cached model batch for unresolved sources with remaining search capacity."""
    pending = [
        ref
        for ref in references
        if search_trigger(records[ref.id], session.settings)
        and has_search_evidence(ref)
        and any(
            not session.stop_reason(provider, ref.id)
            for provider in ["crossref", *session.settings.providers]
        )
    ]
    if not pending or session.deadline - monotonic() < 1:
        return
    plan = reference_query_planning.plan_reference_queries(
        pending,
        candidates,
        session.cache_directory / "plans",
        session.settings,
        session.report,
        model_configuration(configuration, session.settings, session.deadline),
        session.cancelled,
    )
    originals = {ref.id: ref for ref in pending}
    traces = {trace.reference_id: trace for trace in session.report.searches}
    for proposal in plan.queries:
        original = originals[proposal.reference_id]
        refined = refine_search_evidence(original, proposal)
        traces[original.id].trigger += "; " + proposal.reason
        query = papers.PaperReference(
            id=original.id, title=proposal.title, authors=proposal.authors, year=proposal.year
        )
        for provider in ["crossref", *provider_order(original, session.settings)]:
            if not search_trigger(records[original.id], session.settings):
                break
            candidates[original.id].extend(session.search(provider, query, traces[original.id]))
            records[original.id] = resolved_record(
                original, candidates[original.id], source_sha256, refined=refined
            )
        mark_lookup_failure(records[original.id], traces[original.id])


def refine_search_evidence(
    original: papers.PaperReference, proposal: reference_query_planning.ReferenceQuery
) -> papers.PaperReference:
    """Use validated title cleanup without overriding existing author or edition-year evidence."""
    reference_query_planning.validate_queries(
        reference_query_planning.ReferenceQueries(queries=[proposal]), {original.id: original}
    )
    refined = evidence_reference(original)
    original_title = resolution.normalized_words(original.title)
    proposed_title = resolution.normalized_words(proposal.title)
    if not original_title or f" {proposed_title} " in f" {original_title} ":
        refined.title = proposal.title
    if not refined.authors:
        refined.authors = proposal.authors
    return refined


def discover_references(
    paper: papers.PaperDocument,
    pages: list[str],
    source_sha256: str,
    output_directory: Path,
    cache_directory: Path,
    *,
    settings: models.DiscoverySettings,
    configuration: structured_generation.ModelConfiguration,
    timeout_seconds: float,
    cancelled: Callable[[], bool],
    providers: dict[str, resolution.Lookup] | None = None,
) -> ReferenceDiscoveryResult:
    """Audit source coverage, recover grounded entries and identify only unresolved literature."""
    if not 0 < timeout_seconds <= 240:
        raise ValueError("Reference discovery timeout must be between 0 and 240 seconds")
    deadline = monotonic() + timeout_seconds
    report = models.DiscoveryReport()
    recovery = bibliography_recovery.recover_bibliography(
        paper,
        pages,
        cache_directory / "bibliography",
        configuration=model_configuration(configuration, settings, deadline),
        cancelled=cancelled,
        allow_model=settings.max_model_calls > 0 and deadline - monotonic() >= 1,
        timeout_seconds=max(0.1, deadline - monotonic()),
        retry_generation=settings.retry_generation,
    )
    report.cache_hits += int(recovery.report.cache_reused)
    report.model_calls += int(
        not recovery.report.cache_reused and recovery.report.model_status in {"completed", "failed"}
    )
    report.warnings.extend(recovery.report.unresolved_issues)
    session = ReferenceSearchSession(
        cache_directory / "lookups",
        settings,
        report,
        deadline,
        cancelled,
        providers if providers is not None else available_providers(),
    )
    configured = [*settings.providers, *(["unpaywall"] if settings.find_open_access else [])]
    for provider in configured:
        if provider not in session.providers:
            report.warnings.append(f"{provider} is not configured; add its documented credentials.")
    original_references = [
        papers.PaperReference(id="__source__", **paper.metadata.model_dump()),
        *recovery.paper.references,
    ]
    references = unique_search_references(original_references)
    records: dict[str, literature_models.LiteratureRecord] = {}
    candidates: dict[str, list[literature_models.Candidate]] = {}
    for reference in references:
        records[reference.id], candidates[reference.id] = search_reference(
            reference, source_sha256, session
        )
    refine_unresolved(references, records, candidates, session, configuration, source_sha256)
    for reference in references:
        if records[reference.id].resolution.status == "matched":
            write_json_atomically(
                confirmed_record_path(reference, source_sha256, session),
                records[reference.id].model_dump(mode="json"),
            )
    collected = collect_literature(
        recovery.paper, references, original_references, records, source_sha256
    )
    if settings.find_open_access:
        enrich_access(collected, session)
    write_json_atomically(
        output_directory / "reference-discovery.json", report.model_dump(mode="json")
    )
    return ReferenceDiscoveryResult(
        paper=recovery.paper, literature=collected, report=report, bibliography=recovery.report
    )


def enrich_access(
    records: list[literature_models.LiteratureRecord], session: ReferenceSearchSession
) -> None:
    """Look for missing access links only after a work's DOI has been confirmed."""
    for record in records:
        if (
            record.resolution.status != "matched"
            or not record.metadata.doi
            or record.metadata.open_access_url
        ):
            continue
        reference_id = record.extracted[0].id
        trace = models.ReferenceSearch(
            reference_id=reference_id, trigger="Missing open-access location"
        )
        session.report.searches.append(trace)
        candidates = session.search(
            "unpaywall", papers.PaperReference(id=reference_id, doi=record.metadata.doi), trace
        )
        if candidates:
            record.metadata.open_access_url = candidates[0].metadata.open_access_url
            record.metadata.open_access_pdf_url = candidates[0].metadata.open_access_pdf_url


def collect_literature(
    paper: papers.PaperDocument,
    references: list[papers.PaperReference],
    originals: list[papers.PaperReference],
    records: dict[str, literature_models.LiteratureRecord],
    source_sha256: str,
) -> list[literature_models.LiteratureRecord]:
    """Reuse citation attachment after merging only confirmed work identities."""
    collected: dict[str, literature_models.LiteratureRecord] = {}
    for index, (reference, original) in enumerate(zip(references, originals, strict=True)):
        record = records[reference.id].model_copy(deep=True)
        record.extracted = [original]
        record.reference_ids = [] if index == 0 else [original.id]
        resolution.collect_record(collected, record)
    resolution.attach_occurrences(paper, source_sha256, collected)
    return list(collected.values())


def unique_search_references(
    references: list[papers.PaperReference],
) -> list[papers.PaperReference]:
    """Separate duplicate provider IDs internally without changing their citation evidence."""
    counts = Counter(ref.id for ref in references)
    occupied = set(counts)
    result = []
    for index, reference in enumerate(references):
        copied = reference.model_copy(deep=True)
        if index and counts[reference.id] > 1:
            copied.id = f"{reference.id}__entry_{index}"
            while copied.id in occupied:
                copied.id += "_"
            occupied.add(copied.id)
        result.append(copied)
    return result
