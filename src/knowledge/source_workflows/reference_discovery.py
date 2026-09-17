"""Recover and identify references with bounded, evidence-driven fallback searches."""

import os
import re
from collections import Counter
from collections.abc import Callable
from itertools import islice
from pathlib import Path
from time import monotonic

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
from knowledge.runtime_support.workflow_event_log import record_event
from knowledge.source_workflows import bibliography_recovery, reference_query_planning
from knowledge.source_workflows.reference_discovery_models import (
    ReferenceDiscoveryResult,
    ReferenceSearchState,
)
from knowledge.source_workflows.reference_query_models import (
    MAX_QUERY_CANDIDATES,
    MAX_QUERY_REFERENCES,
    ReferenceQueryEvidence,
)
from knowledge.source_workflows.reference_search import (
    ReferenceSearchSession,
    query_text,
    request_key,
)


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


def resolved_record(
    reference: papers.PaperReference,
    candidates: list[literature_models.Candidate],
    source_sha256: str,
    refined: papers.PaperReference | None = None,
) -> literature_models.LiteratureRecord:
    """Keep identity decisions deterministic and retain the original extraction evidence."""
    corroborated = evidence_reference(refined or reference)
    result = resolution.resolve_reference(corroborated, candidates)
    role = "source" if reference.id == "__source__" else "reference"
    record = resolution.build_record(reference, result, source_sha256, role)
    if result.status != "matched":
        return record
    for field in ("title", "authors", "year", "venue"):
        if getattr(record.metadata, field) or not getattr(corroborated, field):
            continue
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


def prepare_reference_search(
    original: papers.PaperReference,
    reference: papers.PaperReference,
    source_sha256: str,
    session: ReferenceSearchSession,
) -> ReferenceSearchState:
    """Create one inspectable search state without spending provider capacity."""
    state = ReferenceSearchState(
        original=original,
        reference=reference,
        record=resolved_record(reference, [], source_sha256),
        trace=models.ReferenceSearch(reference_id=reference.id, trigger="Initial identification"),
    )
    session.report.searches.append(state.trace)
    if not has_search_evidence(reference):
        state.trace.trigger = "Insufficient bibliographic evidence; review required"
    return state


def search_initial_round(
    searches: list[ReferenceSearchState], session: ReferenceSearchSession
) -> None:
    """Give every searchable source one identity lookup before any fallback request."""
    for state in searches:
        if has_search_evidence(state.reference):
            identify_reference(state, session)


def fallback_plan(
    state: ReferenceSearchState, settings: models.DiscoverySettings
) -> tuple[papers.PaperReference, list[str]] | None:
    """Build the deterministic provider sequence for one still-incomplete source."""
    if not has_search_evidence(state.reference):
        return None
    trigger = search_trigger(state.record, settings)
    state.trace.trigger = trigger or "Complete; fallback skipped"
    if not trigger:
        return None
    query = evidence_reference(state.reference)
    providers = provider_order(state.reference, settings)
    if query.doi:
        query.doi = None
        providers.insert(0, "crossref")
    return query, providers


def search_fallback_rounds(
    searches: list[ReferenceSearchState], session: ReferenceSearchSession
) -> None:
    """Search one provider per source per round so later references retain capacity."""
    plans = [
        (state, plan)
        for state in searches
        if (plan := fallback_plan(state, session.settings)) is not None
    ]
    provider_count = max((len(plan[1]) for _, plan in plans), default=0)
    for index in range(provider_count):
        for state, (query, providers) in plans:
            if index >= len(providers) or not search_trigger(state.record, session.settings):
                continue
            search_provider(state, query, providers[index], session)
    for state, _ in plans:
        mark_lookup_failure(state.record, state.trace)


def identify_reference(state: ReferenceSearchState, session: ReferenceSearchSession) -> None:
    """Reuse a confirmed identity or perform the initial provider lookup."""
    path = confirmed_record_path(state.reference, state.record.source_sha256, session)
    if not path.exists():
        state.candidates = session.search(
            initial_provider(state.reference, session.settings), state.reference, state.trace
        )
        state.record = resolved_record(
            state.reference, state.candidates, state.record.source_sha256
        )
        return
    previous = literature_models.LiteratureRecord.model_validate_json(path.read_text())
    session.report.cache_hits += 1
    state.candidates = previous.resolution.candidates
    query = models.SearchQuery(
        provider=previous.resolution.provider or "cache",
        query=query_text(state.reference),
        status="success",
        cached=True,
        candidate_count=len(state.candidates),
        message="Reused confirmed identity.",
    )
    state.trace.queries.append(query)
    session.record_query(state.reference.id, query)
    if not search_trigger(previous, session.settings):
        state.record = previous
        return
    state.record = resolved_record(state.reference, state.candidates, state.record.source_sha256)


def search_provider(
    state: ReferenceSearchState,
    query: papers.PaperReference,
    provider: str,
    session: ReferenceSearchSession,
    refined: papers.PaperReference | None = None,
) -> None:
    """Apply one provider result to one source's deterministic resolution."""
    state.candidates.extend(session.search(provider, query, state.trace))
    state.record = resolved_record(
        state.reference, state.candidates, state.record.source_sha256, refined=refined
    )


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
    if crossref_client.normalize_doi(reference.doi) or not extracted_isbn(reference):
        return "crossref"
    return next(
        (
            provider
            for provider in ("dnb", "openlibrary", "google_books")
            if provider in settings.providers
        ),
        "crossref",
    )


def mark_lookup_failure(
    record: literature_models.LiteratureRecord, trace: models.ReferenceSearch
) -> None:
    """Distinguish unavailable providers and exhausted budgets from an ordinary no-match result."""
    if record.resolution.status != "unmatched":
        return
    failed = [query for query in trace.queries if query.status in {"error", "budget", "backoff"}]
    if not failed:
        return
    record.resolution.message += " " + " ".join(dict.fromkeys(query.message for query in failed))
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
    searches: list[ReferenceSearchState],
    session: ReferenceSearchSession,
    configuration: structured_generation.ModelConfiguration,
) -> None:
    """Plan one bounded batch for unresolved sources with remaining search capacity."""
    audit = session.report.refinement
    session.release_reserved_requests()
    unresolved = {
        state.reference.id: state
        for state in searches
        if search_trigger(state.record, session.settings) and has_search_evidence(state.reference)
    }
    if not unresolved:
        audit.reason = "No unresolved source has sufficient evidence for refinement."
        return
    if session.deadline - monotonic() < 1:
        audit.status = "skipped"
        audit.reason = "Time budget was exhausted before query refinement."
        return
    pending = {key: state for key, state in unresolved.items() if can_refine(state, session)}
    if not pending:
        audit.status = "skipped"
        audit.reason = refinement_unavailable_reason(list(unresolved.values()), session)
        return
    requests_before = session.report.requests
    models_before = session.report.model_calls
    cache_before = session.report.cache_hits
    warnings_before = len(session.report.warnings)
    if session.event_directory is not None:
        record_event(
            session.event_directory,
            "reference_refinement_started",
            references=len(pending),
            reserved_requests=audit.reserved_requests,
            requests=session.report.requests,
            model_calls=session.report.model_calls,
        )
    plan = reference_query_planning.plan_reference_queries(
        planning_evidence(list(pending.values())),
        session.cache_directory / "plans",
        session.settings,
        session.report,
        model_configuration(configuration, session.settings, session.deadline),
        session.cancelled,
    )
    audit.planned_queries = len(plan.queries)
    audit.model_called = session.report.model_calls > models_before
    audit.cache_reused = session.report.cache_hits > cache_before and not audit.model_called
    if not plan.queries:
        if len(session.report.warnings) > warnings_before:
            audit.status = "failed"
            audit.reason = "Query planning failed; inspect the discovery warnings."
        elif models_before >= session.settings.max_model_calls and not audit.cache_reused:
            audit.status = "skipped"
            audit.reason = "No cached query plan exists and the model-call budget is exhausted."
        else:
            audit.status = "completed"
            audit.reason = "The query planner returned no grounded search variants."
        return
    search_refinement_rounds(pending, plan.queries, session)
    audit.status = "completed"
    audit.reason = "Grounded query variants were searched deterministically."
    audit.requests = session.report.requests - requests_before


def refinement_unavailable_reason(
    searches: list[ReferenceSearchState], session: ReferenceSearchSession
) -> str:
    """Retain the concrete capacity reasons that prevented query refinement."""
    reasons = {
        reason
        for state in searches
        for provider in ["crossref", *session.settings.providers]
        if (reason := session.stop_reason(provider, state.reference.id)) is not None
    }
    if not reasons:
        return "No configured provider can run the proposed refinement queries."
    return "Query refinement unavailable: " + " ".join(sorted(reasons))


def planning_evidence(searches: list[ReferenceSearchState]) -> list[ReferenceQueryEvidence]:
    """Select bounded provider evidence without rebuilding parallel reference dictionaries."""
    return [
        ReferenceQueryEvidence(
            reference=state.reference, candidates=state.candidates[:MAX_QUERY_CANDIDATES]
        )
        for state in islice(searches, MAX_QUERY_REFERENCES)
    ]


def can_refine(state: ReferenceSearchState, session: ReferenceSearchSession) -> bool:
    """Require unresolved evidence and capacity at at least one configured provider."""
    if not search_trigger(state.record, session.settings) or not has_search_evidence(
        state.reference
    ):
        return False
    return any(
        not session.stop_reason(provider, state.reference.id)
        for provider in ["crossref", *session.settings.providers]
    )


def search_refinement_rounds(
    pending: dict[str, ReferenceSearchState],
    proposals: list[reference_query_planning.ReferenceQuery],
    session: ReferenceSearchSession,
) -> None:
    """Distribute refined provider queries fairly across all proposed references."""
    plans = [
        refinement_search_plan(pending[proposal.reference_id], proposal, session)
        for proposal in proposals
    ]
    provider_count = max((len(providers) for _, _, _, providers in plans), default=0)
    for index in range(provider_count):
        for state, refined, query, providers in plans:
            if index >= len(providers) or not search_trigger(state.record, session.settings):
                continue
            search_provider(state, query, providers[index], session, refined=refined)
    for state, _, _, _ in plans:
        mark_lookup_failure(state.record, state.trace)


def refinement_search_plan(
    state: ReferenceSearchState,
    proposal: reference_query_planning.ReferenceQuery,
    session: ReferenceSearchSession,
) -> tuple[ReferenceSearchState, papers.PaperReference, papers.PaperReference, list[str]]:
    """Prepare one grounded refinement without asserting a source identity."""
    refined = refine_search_evidence(state.reference, proposal)
    state.trace.trigger += "; " + proposal.reason
    query = papers.PaperReference(
        id=state.reference.id, title=proposal.title, authors=proposal.authors, year=proposal.year
    )
    providers = ["crossref", *provider_order(state.reference, session.settings)]
    return state, refined, query, providers


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
    record_event(
        output_directory,
        "reference_discovery_started",
        max_requests=settings.max_requests,
        max_requests_per_reference=settings.max_requests_per_reference,
        max_model_calls=settings.max_model_calls,
    )
    session = ReferenceSearchSession(
        cache_directory=cache_directory / "lookups",
        settings=settings,
        report=models.DiscoveryReport(),
        deadline=deadline,
        cancelled=cancelled,
        providers=providers if providers is not None else available_providers(),
        event_directory=output_directory,
    )
    recovery = recover_source_bibliography(paper, pages, cache_directory, configuration, session)
    record_event(
        output_directory,
        "bibliography_recovery_finished",
        status=recovery.report.status,
        model_status=recovery.report.model_status,
        cache_reused=recovery.report.cache_reused,
        original_count=recovery.report.original_count,
        resulting_count=recovery.report.resulting_count,
        model_calls=session.report.model_calls,
    )
    searches = identify_sources(paper, recovery.paper, source_sha256, session)
    statuses = Counter(state.record.resolution.status for state in searches)
    record_event(
        output_directory,
        "ordinary_reference_search_finished",
        requests=session.report.requests,
        reserved_requests=session.report.refinement.reserved_requests,
        resolution_counts=dict(statuses),
    )
    refine_unresolved(searches, session, configuration)
    refinement_event = {
        "not_needed": "reference_refinement_not_needed",
        "skipped": "reference_refinement_skipped",
        "failed": "reference_refinement_failed",
        "completed": "reference_refinement_completed",
    }[session.report.refinement.status]
    record_event(
        output_directory,
        refinement_event,
        **session.report.refinement.model_dump(mode="json"),
    )
    save_confirmed_sources(searches, session)
    collected = collect_literature(recovery.paper, searches, source_sha256)
    if settings.find_open_access:
        enrich_access(collected, session)
    write_json_atomically(
        output_directory / "reference-discovery.json", session.report.model_dump(mode="json")
    )
    record_event(
        output_directory,
        "reference_discovery_finished",
        requests=session.report.requests,
        cache_hits=session.report.cache_hits,
        model_calls=session.report.model_calls,
        literature_records=len(collected),
    )
    return ReferenceDiscoveryResult(
        paper=recovery.paper,
        literature=collected,
        report=session.report,
        bibliography=recovery.report,
    )


def recover_source_bibliography(
    paper: papers.PaperDocument,
    pages: list[str],
    cache_directory: Path,
    configuration: structured_generation.ModelConfiguration,
    session: ReferenceSearchSession,
) -> bibliography_recovery.BibliographyRecoveryResult:
    """Recover bibliography coverage and account for its bounded model work."""
    recovery = bibliography_recovery.recover_bibliography(
        paper,
        pages,
        cache_directory / "bibliography",
        configuration=model_configuration(configuration, session.settings, session.deadline),
        cancelled=session.cancelled,
        allow_model=session.settings.max_model_calls > 0 and session.deadline - monotonic() >= 1,
        timeout_seconds=max(0.1, session.deadline - monotonic()),
        retry_generation=session.settings.retry_generation,
    )
    session.report.cache_hits += int(recovery.report.cache_reused)
    session.report.model_calls += int(
        not recovery.report.cache_reused and recovery.report.model_status in {"completed", "failed"}
    )
    session.report.warnings.extend(recovery.report.unresolved_issues)
    return recovery


def identify_sources(
    paper: papers.PaperDocument,
    recovered: papers.PaperDocument,
    source_sha256: str,
    session: ReferenceSearchSession,
) -> list[ReferenceSearchState]:
    """Assign distinct search identities and identify the source document and its references."""
    configured = [*session.settings.providers]
    if session.settings.find_open_access:
        configured.append("unpaywall")
    session.report.warnings.extend(
        f"{provider} is not configured; add its documented credentials."
        for provider in configured
        if provider not in session.providers
    )
    originals = [
        papers.PaperReference(id="__source__", **paper.metadata.model_dump()),
        *recovered.references,
    ]
    references = unique_search_references(originals)
    searches = [
        prepare_reference_search(original, reference, source_sha256, session)
        for original, reference in zip(originals, references, strict=True)
    ]
    session.report.refinement.reserved_requests = session.reserve_refinement_requests(
        sum(has_search_evidence(state.reference) for state in searches)
    )
    search_initial_round(searches, session)
    search_fallback_rounds(searches, session)
    return searches


def save_confirmed_sources(
    searches: list[ReferenceSearchState], session: ReferenceSearchSession
) -> None:
    """Persist confirmed identities independently of unresolved-search retries."""
    for state in searches:
        if state.record.resolution.status != "matched":
            continue
        write_json_atomically(
            confirmed_record_path(state.reference, state.record.source_sha256, session),
            state.record.model_dump(mode="json"),
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
        if not candidates:
            continue
        record.metadata.open_access_url = candidates[0].metadata.open_access_url
        record.metadata.open_access_pdf_url = candidates[0].metadata.open_access_pdf_url


def collect_literature(
    paper: papers.PaperDocument,
    searches: list[ReferenceSearchState],
    source_sha256: str,
) -> list[literature_models.LiteratureRecord]:
    """Restore original reference IDs before merging identities and attaching citations."""
    collected: dict[str, literature_models.LiteratureRecord] = {}
    for index, state in enumerate(searches):
        record = state.record.model_copy(deep=True)
        record.extracted = [state.original]
        record.reference_ids = [] if index == 0 else [state.original.id]
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
        result.append(copied)
        if not index or counts[reference.id] <= 1:
            continue
        copied.id = available_reference_id(f"{reference.id}__entry_{index}", occupied)
        occupied.add(copied.id)
    return result


def available_reference_id(proposed_id: str, occupied: set[str]) -> str:
    """Find an unused internal identifier without changing source evidence."""
    while proposed_id in occupied:
        proposed_id += "_"
    return proposed_id
