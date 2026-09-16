from collections import Counter
from time import monotonic

import pytest

from knowledge.literature import literature_resolution
from knowledge.literature.literature_models import Candidate, LiteratureMetadata
from knowledge.literature.reference_discovery_models import (
    DiscoveryReport,
    DiscoverySettings,
    ReferenceSearch,
)
from knowledge.literature.structured_paper_models import (
    PaperDocument,
    PaperMetadata,
    PaperReference,
)
from knowledge.model_integration.structured_generation import ModelConfiguration
from knowledge.source_workflows import reference_discovery as discovery
from knowledge.source_workflows import reference_query_planning as planning
from knowledge.source_workflows import reference_search
from knowledge.source_workflows.bibliography_recovery_models import (
    BibliographyAudit,
    BibliographyRecoveryResult,
)


@pytest.fixture(autouse=True)
def isolated_discovery(monkeypatch):
    def recover(paper, *_args, **_kwargs):
        return BibliographyRecoveryResult(
            paper=paper.model_copy(deep=True),
            report=BibliographyAudit(
                status="consistent",
                original_count=len(paper.references),
                detected_count=len(paper.references),
                resulting_count=len(paper.references),
                model_status="not_needed",
            ),
        )

    monkeypatch.setattr(discovery.bibliography_recovery, "recover_bibliography", recover)
    monkeypatch.setattr(
        reference_search.ReferenceSearchSession, "wait_for_provider", lambda *_: None
    )


def reference(identifier="r1", **changes):
    fields = {
        "id": identifier,
        "title": "A scientific study",
        "authors": ["Alice Smith"],
        "year": "2020",
        "raw": "Smith (2020). A scientific study.",
    }
    return PaperReference.model_validate(fields | changes)


def candidate(ref=None, provider="crossref", identifier="work-1", **changes):
    ref = ref or reference()
    fields = ref.model_dump(exclude={"id", "raw"}) | changes
    return Candidate(
        provider=provider,
        provider_id=identifier,
        method="bibliographic",
        metadata=LiteratureMetadata.model_validate(fields),
    )


def document(*references, metadata=None):
    return PaperDocument(
        markdown="Source text",
        provider="grobid",
        metadata=metadata
        or PaperMetadata(title="Uploaded paper", authors=["Ursula Jones"], year="2021"),
        references=list(references),
    )


def run_discovery(
    tmp_path, paper, providers, settings=None, source_sha="a" * 64, cancelled=lambda: False
):
    return discovery.discover_references(
        paper,
        ["Source text"],
        source_sha,
        tmp_path / "output",
        tmp_path / "cache",
        settings=settings or DiscoverySettings(max_model_calls=0),
        configuration=ModelConfiguration(),
        timeout_seconds=30,
        cancelled=cancelled,
        providers=providers,
    )


def providers_recording(calls, reference_result=None, fallback_result=None):
    def crossref(ref, *_):
        calls.append(("crossref", ref.model_copy(deep=True)))
        if ref.title == "Uploaded paper":
            return [candidate(ref, identifier="uploaded-paper")]
        return reference_result(ref) if reference_result else []

    def fallback(name):
        def lookup(ref, *_):
            calls.append((name, ref.model_copy(deep=True)))
            return fallback_result(name, ref) if fallback_result else []

        return lookup

    return {
        "crossref": crossref,
        **{name: fallback(name) for name in ("dnb", "openalex", "openlibrary")},
    }


def test_complete_crossref_record_skips_fallback_and_model(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        planning.structured_generation,
        "generate",
        lambda *_a, **_k: pytest.fail("Unexpected model call"),
    )
    result = run_discovery(
        tmp_path,
        document(reference()),
        providers_recording(calls, lambda ref: [candidate(ref)]),
        DiscoverySettings(max_model_calls=2),
    )
    assert [name for name, _ in calls] == ["crossref", "crossref"]
    assert all(record.resolution.status == "matched" for record in result.literature)
    assert result.report.model_calls == 0


def test_optional_doi_and_venue_do_not_trigger_fallback(tmp_path):
    calls = []
    result = run_discovery(
        tmp_path, document(reference()), providers_recording(calls, lambda ref: [candidate(ref)])
    )
    record = next(record for record in result.literature if record.role == "reference")
    assert record.metadata.doi is None and record.metadata.venue is None
    assert [name for name, _ in calls] == ["crossref", "crossref"]


def test_required_missing_field_invokes_fallback_and_stops_on_complete_identity(tmp_path):
    calls = []
    providers = providers_recording(
        calls,
        lambda ref: [candidate(ref, doi="10.1234/work")],
        lambda name, ref: [
            candidate(ref, provider=name, doi="10.1234/work", publisher="Publisher")
        ],
    )
    result = run_discovery(
        tmp_path,
        document(reference()),
        providers,
        DiscoverySettings(
            providers=["dnb", "openalex"],
            required_fields=["title", "authors", "year", "publisher"],
            max_model_calls=0,
        ),
    )
    record = next(record for record in result.literature if record.role == "reference")
    assert record.metadata.publisher == "Publisher"
    calls_for_reference = [name for name, ref in calls if ref.title == "A scientific study"]
    assert calls_for_reference == ["crossref", "openalex"]


def test_unsuccessful_results_are_reused_without_requests_on_repeated_run(tmp_path):
    calls = []
    providers = providers_recording(calls)
    paper = document(reference())
    first = run_discovery(tmp_path, paper, providers)
    assert first.report.requests > 0
    calls.clear()
    second = run_discovery(tmp_path, paper, providers)
    assert calls == []
    assert second.report.requests == 0
    assert second.report.cache_hits > 0


def test_manual_retry_revision_repeats_cached_unsuccessful_queries(tmp_path):
    calls = []
    providers = providers_recording(calls)
    paper = document(reference())
    run_discovery(tmp_path, paper, providers)
    expected = sum(ref.id == "r1" for _, ref in calls)
    calls.clear()
    result = run_discovery(
        tmp_path, paper, providers, DiscoverySettings(max_model_calls=0, retry_generation=1)
    )
    assert len(calls) == expected
    assert result.report.requests == expected
    assert all(ref.id == "r1" for _, ref in calls)
    assert (
        next(record for record in result.literature if record.role == "source").resolution.status
        == "matched"
    )


def test_manual_retry_preserves_confirmed_complete_records_without_queries(tmp_path):
    calls = []
    providers = providers_recording(calls, lambda ref: [candidate(ref)])
    paper = document(reference())
    run_discovery(tmp_path, paper, providers)
    calls.clear()
    result = run_discovery(
        tmp_path, paper, providers, DiscoverySettings(max_model_calls=0, retry_generation=1)
    )
    assert calls == []
    assert result.report.requests == 0
    assert all(record.resolution.status == "matched" for record in result.literature)


def test_changed_source_metadata_and_reference_evidence_invalidate_effective_queries(tmp_path):
    calls = []
    providers = providers_recording(calls)
    run_discovery(tmp_path, document(reference()), providers)
    calls.clear()
    changed = document(
        reference(raw="Smith (2020). A scientific study. Updated edition."),
        metadata=PaperMetadata(
            title="Changed uploaded paper", authors=["Ursula Jones"], year="2021"
        ),
    )
    result = run_discovery(tmp_path, changed, providers, source_sha="b" * 64)
    assert result.report.requests > 0
    assert any(ref.title == "Changed uploaded paper" for _, ref in calls)
    assert any(ref.raw and "Updated edition" in ref.raw for _, ref in calls)
    assert all(record.source_sha256 == "b" * 64 for record in result.literature)


def test_total_request_budget_stops_all_further_network_requests(tmp_path):
    calls = []
    result = run_discovery(
        tmp_path,
        document(reference(), reference("r2", title="Another study")),
        providers_recording(calls),
        DiscoverySettings(max_model_calls=0, max_requests=2),
    )
    assert len(calls) == result.report.requests == 2
    assert any(
        query.status == "budget" for trace in result.report.searches for query in trace.queries
    )


def test_per_reference_budget_leaves_capacity_for_other_references(tmp_path):
    calls = []
    result = run_discovery(
        tmp_path,
        document(reference(), reference("r2", title="Another study")),
        providers_recording(calls),
        DiscoverySettings(max_model_calls=0, max_requests_per_reference=1),
    )
    assert result.report.requests == 3
    assert Counter(ref.id for _, ref in calls) == {"__source__": 1, "r1": 1, "r2": 1}


def test_rate_limit_disables_only_the_affected_provider_for_remaining_run(tmp_path):
    calls = []
    providers = providers_recording(calls)

    def limited(ref, *_):
        calls.append(("crossref", ref.model_copy(deep=True)))
        raise ValueError("upstream HTTP 429 with secret detail")

    providers["crossref"] = limited
    result = run_discovery(tmp_path, document(reference()), providers)
    assert sum(name == "crossref" for name, _ in calls) == 1
    assert any(name == "dnb" for name, _ in calls)
    assert any(
        query.status == "backoff" for trace in result.report.searches for query in trace.queries
    )
    assert "secret detail" not in result.report.model_dump_json()


def test_cancellation_propagates_without_downstream_provider_calls(tmp_path):
    calls = []
    with pytest.raises(InterruptedError):
        run_discovery(
            tmp_path, document(reference()), providers_recording(calls), cancelled=lambda: True
        )
    assert calls == []


def test_same_doi_from_multiple_providers_is_one_identity_with_richer_metadata():
    ref = reference()
    first = candidate(ref, doi="10.1234/WORK")
    second = candidate(
        ref, provider="openalex", identifier="W1", doi="10.1234/work", publisher="Publisher"
    )
    result = literature_resolution.resolve_reference(ref, [first, second])
    assert result.status == "matched"
    assert result.candidates[0].metadata.publisher == "Publisher"
    assert len(result.candidates) == 2


def test_different_book_editions_remain_ambiguous():
    ref = reference()
    first = candidate(
        ref, provider="dnb", identifier="edition-one", work_type="book", isbn=["9783593379784"]
    )
    second = candidate(
        ref, provider="dnb", identifier="edition-two", work_type="book", isbn=["9783593413990"]
    )
    result = discovery.resolved_record(ref, [first, second], "a" * 64)
    assert result.resolution.status == "ambiguous"
    assert result.metadata.isbn == []


def test_failed_doi_lookup_retries_title_and_corroborates_original_evidence(tmp_path):
    calls = []
    providers = providers_recording(calls, lambda ref: [] if ref.doi else [candidate(ref)])
    result = run_discovery(tmp_path, document(reference(doi="10.1234/wrong")), providers)
    reference_calls = [ref for _, ref in calls if ref.id == "r1"]
    assert [ref.doi for ref in reference_calls] == ["10.1234/wrong", None]
    record = next(record for record in result.literature if record.role == "reference")
    assert record.resolution.status == "matched"
    assert record.extracted[0].doi == "10.1234/wrong"


def test_chapter_evidence_cannot_be_confirmed_as_containing_book():
    ref = reference(raw="Smith (2020). A scientific study. In: Collected essays, pp. 1-10.")
    result = discovery.resolved_record(ref, [candidate(ref, work_type="book")], "a" * 64)
    assert result.resolution.status == "unmatched"


def test_no_provider_query_without_bibliographic_evidence(tmp_path):
    calls = []
    paper = document(PaperReference(id="empty"), metadata=PaperMetadata())
    result = run_discovery(tmp_path, paper, providers_recording(calls))
    assert calls == []
    assert result.report.requests == 0


def test_duplicate_reference_ids_preserve_each_original_record(tmp_path):
    calls = []
    refs = [
        reference("same", title="First scientific study", raw="First original reference"),
        reference("same", title="Second scientific study", raw="Second original reference"),
    ]
    result = run_discovery(tmp_path, document(*refs), providers_recording(calls))
    retained = [
        entry
        for record in result.literature
        if record.role == "reference"
        for entry in record.extracted
    ]
    assert sorted(entry.title for entry in retained) == [
        "First scientific study",
        "Second scientific study",
    ]
    assert sorted(entry.raw for entry in retained) == [
        "First original reference",
        "Second original reference",
    ]


def test_model_proposal_cannot_assert_identity_or_add_doi():
    with pytest.raises(ValueError):
        planning.ReferenceQuery.model_validate(
            {
                "reference_id": "r1",
                "title": "A scientific study",
                "reason": "Found",
                "doi": "10.1234/invented",
                "status": "matched",
            }
        )


def test_model_search_variant_must_still_match_original_evidence(tmp_path, monkeypatch):
    calls = []
    ref = reference(
        title="Unreadable original heading",
        raw="Smith (2020). Candidate title mentioned in unrelated context.",
    )
    proposal = planning.ReferenceQueries(
        queries=[
            planning.ReferenceQuery(
                reference_id="r1",
                title="Candidate title",
                authors=["Smith"],
                year="2020",
                reason="Search variant",
            )
        ]
    )
    planning.validate_queries(proposal, {"r1": ref})
    monkeypatch.setattr(planning, "plan_reference_queries", lambda *_a, **_k: proposal)
    providers = providers_recording(
        calls, lambda query: [candidate(query)] if query.title == "Candidate title" else []
    )
    result = run_discovery(
        tmp_path, document(ref), providers, DiscoverySettings(max_model_calls=1, providers=[])
    )
    record = next(record for record in result.literature if record.role == "reference")
    assert record.resolution.status == "unmatched"


@pytest.mark.parametrize(
    "original_title, original_authors",
    [
        (None, []),
        ("A scientific study. Publisher city", ["Alice Smith"]),
    ],
)
def test_grounded_model_fields_enable_matching_without_rewriting_original_evidence(
    tmp_path, monkeypatch, original_title, original_authors
):
    ref = reference(
        title=original_title,
        authors=original_authors,
        year=None,
        raw="Alice Smith (2020). A scientific study. Publisher city.",
    )
    plan = planning.ReferenceQueries(
        queries=[
            planning.ReferenceQuery(
                reference_id="r1",
                title="A scientific study",
                authors=["Alice Smith"],
                year="2020",
                reason="Separate source title from publisher metadata",
            )
        ]
    )
    monkeypatch.setattr(planning.structured_generation, "generate", lambda *_a, **_k: plan)
    calls = []
    providers = providers_recording(
        calls, lambda query: [candidate(query)] if query.title == "A scientific study" else []
    )
    result = run_discovery(
        tmp_path, document(ref), providers, DiscoverySettings(max_model_calls=1, providers=[])
    )
    record = next(record for record in result.literature if record.role == "reference")
    assert record.resolution.status == "matched"
    assert record.metadata.title == "A scientific study"
    assert record.metadata.authors == ["Alice Smith"]
    assert record.metadata.year == "2020"
    assert record.extracted[0] == ref
    assert result.report.model_calls == 1


def test_crossref_rate_limit_still_allows_model_planning_for_dnb(tmp_path, monkeypatch):
    ref = reference(
        title=None, authors=[], year=None, raw="Alice Smith (2020). A scientific study."
    )
    plan = planning.ReferenceQueries(
        queries=[
            planning.ReferenceQuery(
                reference_id="r1",
                title="A scientific study",
                authors=["Alice Smith"],
                year="2020",
                reason="Recover title and author from literal citation",
            )
        ]
    )
    monkeypatch.setattr(planning.structured_generation, "generate", lambda *_a, **_k: plan)
    calls = []

    def crossref_result(_reference):
        raise ValueError("Crossref HTTP 429")

    providers = providers_recording(
        calls,
        crossref_result,
        lambda provider, query: [candidate(query, provider=provider)] if query.title else [],
    )
    result = run_discovery(
        tmp_path, document(ref), providers, DiscoverySettings(max_model_calls=1, providers=["dnb"])
    )
    record = next(record for record in result.literature if record.role == "reference")
    assert record.resolution.status == "matched"
    assert record.resolution.provider == "dnb"
    assert result.report.model_calls == 1
    assert sum(provider == "crossref" and query.id == "r1" for provider, query in calls) == 1
    assert sum(provider == "dnb" for provider, _ in calls) == 1


def test_missing_title_skips_inapplicable_adapters_without_spending_request_budget(tmp_path):
    calls = []
    ref = reference(title=None, authors=[], year=None, raw="Smith (2020). A scientific study.")
    result = run_discovery(
        tmp_path,
        document(ref),
        providers_recording(calls),
        DiscoverySettings(max_model_calls=0, max_requests_per_reference=1),
    )
    assert [provider for provider, query in calls if query.id == "r1"] == ["crossref"]
    trace = next(trace for trace in result.report.searches if trace.reference_id == "r1")
    assert {query.provider for query in trace.queries if query.status == "skipped"} == {
        "dnb",
        "openalex",
        "openlibrary",
    }
    assert result.report.requests == 2


def test_model_plan_rejects_invented_bibliographic_fields():
    proposal = planning.ReferenceQueries(
        queries=[
            planning.ReferenceQuery(
                reference_id="r1",
                title="Completely invented title",
                authors=["Jones"],
                year="2035",
                reason="Guess",
            )
        ]
    )
    with pytest.raises(ValueError, match="original bibliography evidence"):
        planning.validate_queries(proposal, {"r1": reference()})


def test_model_plan_rejects_partial_word_author_and_year_fabrication():
    proposal = planning.ReferenceQueries(
        queries=[
            planning.ReferenceQuery(
                reference_id="r1",
                title="A scientific study",
                authors=["Smit"],
                year="202",
                reason="Truncated source tokens",
            )
        ]
    )
    with pytest.raises(ValueError, match="original bibliography evidence"):
        planning.validate_queries(proposal, {"r1": reference()})


def test_failed_model_planning_is_cached_without_retrying_unchanged_evidence(tmp_path, monkeypatch):
    calls = []

    def fail(*_args, **_kwargs):
        calls.append(True)
        raise RuntimeError("Private upstream failure detail")

    monkeypatch.setattr(planning.structured_generation, "generate", fail)
    settings = DiscoverySettings(max_model_calls=1)
    first, second = DiscoveryReport(), DiscoveryReport()
    for report in (first, second):
        plan = planning.plan_reference_queries(
            [reference()],
            {"r1": []},
            tmp_path,
            settings,
            report,
            ModelConfiguration(),
            lambda: False,
        )
        assert plan.queries == []
        assert "Private upstream" not in report.model_dump_json()
    assert len(calls) == first.model_calls == 1
    assert second.model_calls == 0
    assert second.cache_hits == 1


@pytest.mark.parametrize("budget, expected_access_calls", [(2, 0), (3, 1)])
def test_optional_unpaywall_shares_the_total_request_budget(
    tmp_path, budget, expected_access_calls
):
    calls = []
    providers = providers_recording(calls, lambda ref: [candidate(ref, doi="10.1234/work")])

    def access(ref, *_args):
        calls.append(("unpaywall", ref.model_copy(deep=True)))
        return [candidate(ref, provider="unpaywall", open_access_url="https://example.org/open")]

    providers["unpaywall"] = access
    result = run_discovery(
        tmp_path,
        document(reference()),
        providers,
        DiscoverySettings(max_model_calls=0, find_open_access=True, max_requests=budget),
    )
    assert sum(provider == "unpaywall" for provider, _ in calls) == expected_access_calls
    assert result.report.requests == 2 + expected_access_calls


def test_unpaywall_skips_unconfirmed_dois_absent_dois_and_existing_links(tmp_path):
    calls = []
    refs = [
        reference("unmatched", title="Unmatched title", doi="10.1234/unconfirmed"),
        reference("no-doi", title="No DOI"),
        reference("has-link", title="Known access location"),
    ]

    def found(ref):
        if ref.title == "Unmatched title":
            return []
        if ref.title == "Known access location":
            return [
                candidate(
                    ref,
                    identifier=ref.id,
                    doi="10.1234/existing",
                    open_access_url="https://example.org/existing",
                )
            ]
        return [candidate(ref, identifier=ref.id)]

    providers = providers_recording(calls, found)
    providers["unpaywall"] = lambda *_: pytest.fail("Unpaywall must skip these records")
    result = run_discovery(
        tmp_path,
        document(*refs),
        providers,
        DiscoverySettings(max_model_calls=0, find_open_access=True),
    )
    assert not any(
        trace.trigger == "Missing open-access location" for trace in result.report.searches
    )


def test_recovery_model_call_consumes_the_shared_model_budget(tmp_path, monkeypatch):
    def recover(paper, *_args, **_kwargs):
        return BibliographyRecoveryResult(
            paper=paper,
            report=BibliographyAudit(
                status="consistent",
                original_count=1,
                detected_count=1,
                resulting_count=1,
                model_status="completed",
            ),
        )

    monkeypatch.setattr(discovery.bibliography_recovery, "recover_bibliography", recover)
    monkeypatch.setattr(
        planning.structured_generation,
        "generate",
        lambda *_a, **_k: pytest.fail("Shared model budget already spent"),
    )
    result = run_discovery(
        tmp_path,
        document(reference()),
        providers_recording([]),
        DiscoverySettings(max_model_calls=1),
    )
    assert result.report.model_calls == 1


def test_pacing_exhaustion_is_recorded_without_aborting_discovery(tmp_path, monkeypatch):
    settings = DiscoverySettings(max_model_calls=0)
    report = DiscoveryReport()
    session = reference_search.ReferenceSearchSession(
        tmp_path, settings, report, monotonic() + 5, lambda: False, {"crossref": lambda *_: []}
    )

    def expire(_provider):
        session.deadline = monotonic() - 1

    monkeypatch.setattr(session, "wait_for_provider", expire)
    trace = ReferenceSearch(reference_id="r1", trigger="Unmatched")
    assert session.search("crossref", reference(), trace) == []
    assert trace.queries[0].status == "budget"
    assert report.requests == 0


def test_complete_exact_isbn_match_skips_crossref_and_remaining_providers(tmp_path):
    calls = []
    ref = reference(title=None, authors=[], year=None, raw="ISBN 3-593-37978-3")
    providers = providers_recording(calls)

    def dnb(query, *_args):
        calls.append(("dnb", query.model_copy(deep=True)))
        return [
            Candidate(
                provider="dnb",
                provider_id="977734315",
                method="isbn",
                metadata=LiteratureMetadata(
                    title="Nachhaltigkeit",
                    authors=["Armin Grunwald"],
                    year="2006",
                    isbn=["9783593379784"],
                ),
            )
        ]

    providers["dnb"] = dnb
    result = run_discovery(tmp_path, document(ref), providers)
    assert [provider for provider, query in calls if query.id == "r1"] == ["dnb"]
    record = next(record for record in result.literature if record.role == "reference")
    assert record.resolution.status == "matched"
    assert record.resolution.method == "isbn"
    assert record.metadata.title == "Nachhaltigkeit"
    assert record.extracted[0] == ref
