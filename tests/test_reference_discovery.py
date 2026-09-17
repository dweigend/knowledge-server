from collections.abc import Callable
from pathlib import Path
from typing import Never

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
from knowledge.source_workflows.reference_query_models import (
    ReferenceQueryEvidence,
)


@pytest.fixture(autouse=True)
def isolated_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    def recover(
        paper: PaperDocument, *_args: object, **_kwargs: object
    ) -> BibliographyRecoveryResult:
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
        planning.structured_generation,
        "generate",
        lambda *_args, **_kwargs: planning.ReferenceQueries(),
    )


def reference(identifier: str = "r1", **changes: object) -> PaperReference:
    fields = {
        "id": identifier,
        "title": "A scientific study",
        "authors": ["Alice Smith"],
        "year": "2020",
        "raw": "Smith (2020). A scientific study.",
    }
    return PaperReference.model_validate(fields | changes)


def candidate(
    ref: PaperMetadata | None = None,
    provider: str = "crossref",
    identifier: str = "work-1",
    **changes: object,
) -> Candidate:
    ref = ref or reference()
    fields = ref.model_dump(exclude={"id", "raw"}) | changes
    return Candidate(
        provider=provider,
        provider_id=identifier,
        method="bibliographic",
        metadata=LiteratureMetadata.model_validate(fields),
    )


def document(*references: PaperReference, metadata: PaperMetadata | None = None) -> PaperDocument:
    return PaperDocument(
        markdown="Source text",
        provider="grobid",
        metadata=metadata
        or PaperMetadata(title="Uploaded paper", authors=["Ursula Jones"], year="2021"),
        references=list(references),
    )


def run_discovery(
    tmp_path: Path,
    paper: PaperDocument,
    providers: dict[str, literature_resolution.Lookup],
    settings: DiscoverySettings | None = None,
    source_sha: str = "a" * 64,
    cancelled: Callable[[], bool] = lambda: False,
) -> discovery.ReferenceDiscoveryResult:
    result = discovery.discover_references(
        paper,
        ["Source text"],
        source_sha,
        settings=settings or DiscoverySettings(),
        configuration=ModelConfiguration(),
        cancelled=cancelled,
        providers=providers,
    )
    assert list(tmp_path.rglob("reference-cache")) == []
    return result


def providers_recording(
    calls: list[tuple[str, PaperMetadata]],
    reference_result: Callable[[PaperMetadata], list[Candidate]] | None = None,
    fallback_result: Callable[[str, PaperMetadata], list[Candidate]] | None = None,
) -> dict[str, literature_resolution.Lookup]:
    def crossref(ref: PaperMetadata, *_: object) -> list[Candidate]:
        calls.append(("crossref", ref.model_copy(deep=True)))
        if ref.title == "Uploaded paper":
            return [candidate(ref, identifier="uploaded-paper")]
        return reference_result(ref) if reference_result else []

    def fallback(name: str) -> literature_resolution.Lookup:
        def lookup(ref: PaperMetadata, *_: object) -> list[Candidate]:
            calls.append((name, ref.model_copy(deep=True)))
            return fallback_result(name, ref) if fallback_result else []

        return lookup

    return {
        "crossref": crossref,
        **{name: fallback(name) for name in ("dnb", "openalex", "openlibrary")},
    }


def test_complete_crossref_record_skips_fallback_and_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        DiscoverySettings(),
    )
    assert [name for name, _ in calls] == ["crossref", "crossref"]
    assert all(record.resolution.status == "matched" for record in result.literature)


def test_optional_doi_and_venue_do_not_trigger_fallback(tmp_path: Path) -> None:
    calls = []
    result = run_discovery(
        tmp_path, document(reference()), providers_recording(calls, lambda ref: [candidate(ref)])
    )
    record = next(record for record in result.literature if record.role == "reference")
    assert record.metadata.doi is None and record.metadata.venue is None
    assert [name for name, _ in calls] == ["crossref", "crossref"]


def test_required_missing_field_invokes_fallback_and_stops_on_complete_identity(
    tmp_path: Path,
) -> None:
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
        ),
    )
    record = next(record for record in result.literature if record.role == "reference")
    assert record.metadata.publisher == "Publisher"
    calls_for_reference = [name for name, ref in calls if ref.title == "A scientific study"]
    assert calls_for_reference == ["crossref", "openalex"]


def test_identical_runs_repeat_provider_requests(tmp_path: Path) -> None:
    calls = []
    providers = providers_recording(calls)
    paper = document(reference())
    run_discovery(tmp_path, paper, providers)
    first_calls = [(provider, query.id) for provider, query in calls]
    calls.clear()
    run_discovery(tmp_path, paper, providers)
    assert [(provider, query.id) for provider, query in calls] == first_calls


def test_changed_source_metadata_and_reference_evidence_invalidate_effective_queries(
    tmp_path: Path,
) -> None:
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
    assert any(ref.title == "Changed uploaded paper" for _, ref in calls)
    assert any(ref.raw and "Updated edition" in ref.raw for _, ref in calls)
    assert all(record.source_sha256 == "b" * 64 for record in result.literature)


def test_initial_round_reaches_every_reference_before_fallbacks(tmp_path: Path) -> None:
    calls = []
    refs = [reference(f"r{index}", title=f"Study {index}") for index in range(5)]
    run_discovery(
        tmp_path,
        document(*refs),
        providers_recording(calls),
        DiscoverySettings(providers=[]),
    )
    assert [query.id for _, query in calls] == ["__source__", *[ref.id for ref in refs]]


def test_fallback_rounds_distribute_each_provider_across_references(tmp_path: Path) -> None:
    calls = []
    refs = [reference(f"r{index}", title=f"Study {index}") for index in range(3)]

    def initial_result(query: PaperMetadata) -> list[Candidate]:
        return [candidate(query)] if query.title == "Uploaded paper" else []

    run_discovery(
        tmp_path,
        document(*refs),
        providers_recording(calls, initial_result),
        DiscoverySettings(providers=["dnb", "openalex"]),
    )
    reference_calls = [
        (provider, query.id) for provider, query in calls if query.id != "__source__"
    ]
    assert reference_calls[:3] == [("crossref", ref.id) for ref in refs]
    assert reference_calls[3:6] == [("openalex", ref.id) for ref in refs]


def test_rate_limit_does_not_suppress_later_provider_requests(tmp_path: Path) -> None:
    calls = []
    providers = providers_recording(calls)

    def limited(ref: PaperMetadata, *_: object) -> list[Candidate]:
        calls.append(("crossref", ref.model_copy(deep=True)))
        raise ValueError("upstream HTTP 429 with secret detail")

    providers["crossref"] = limited
    result = run_discovery(tmp_path, document(reference()), providers)
    assert sum(name == "crossref" for name, _ in calls) >= 2
    assert any(name == "dnb" for name, _ in calls)
    assert "secret detail" not in result.report.model_dump_json()


def test_cancellation_propagates_without_downstream_provider_calls(tmp_path: Path) -> None:
    calls = []
    with pytest.raises(InterruptedError):
        run_discovery(
            tmp_path, document(reference()), providers_recording(calls), cancelled=lambda: True
        )
    assert calls == []


def test_same_doi_from_multiple_providers_is_one_identity_with_richer_metadata() -> None:
    ref = reference()
    first = candidate(ref, doi="10.1234/WORK")
    second = candidate(
        ref, provider="openalex", identifier="W1", doi="10.1234/work", publisher="Publisher"
    )
    result = literature_resolution.resolve_reference(ref, [first, second])
    assert result.status == "matched"
    assert result.candidates[0].metadata.publisher == "Publisher"
    assert len(result.candidates) == 2


def test_different_book_editions_remain_ambiguous() -> None:
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


def test_failed_doi_lookup_retries_title_and_corroborates_original_evidence(tmp_path: Path) -> None:
    calls = []
    providers = providers_recording(calls, lambda ref: [] if ref.doi else [candidate(ref)])
    result = run_discovery(tmp_path, document(reference(doi="10.1234/wrong")), providers)
    reference_calls = [ref for _, ref in calls if ref.id == "r1"]
    assert [ref.doi for ref in reference_calls] == ["10.1234/wrong", None]
    record = next(record for record in result.literature if record.role == "reference")
    assert record.resolution.status == "matched"
    assert record.extracted[0].doi == "10.1234/wrong"


def test_chapter_evidence_cannot_be_confirmed_as_containing_book() -> None:
    ref = reference(raw="Smith (2020). A scientific study. In: Collected essays, pp. 1-10.")
    result = discovery.resolved_record(ref, [candidate(ref, work_type="book")], "a" * 64)
    assert result.resolution.status == "unmatched"
    assert result.resolution.rejections[0].reasons == [
        "A cited chapter cannot be confirmed as its containing book."
    ]


def test_no_provider_query_without_bibliographic_evidence(tmp_path: Path) -> None:
    calls = []
    paper = document(PaperReference(id="empty"), metadata=PaperMetadata())
    run_discovery(tmp_path, paper, providers_recording(calls))
    assert calls == []


def test_duplicate_reference_ids_preserve_each_original_record(tmp_path: Path) -> None:
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
    assert sorted(entry.title or "" for entry in retained) == [
        "First scientific study",
        "Second scientific study",
    ]
    assert sorted(entry.raw or "" for entry in retained) == [
        "First original reference",
        "Second original reference",
    ]


def test_model_proposal_cannot_assert_identity_or_add_doi() -> None:
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


def test_model_search_variant_must_still_match_original_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    result = run_discovery(tmp_path, document(ref), providers, DiscoverySettings(providers=[]))
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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    original_title: str | None,
    original_authors: list[str],
) -> None:
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
    result = run_discovery(tmp_path, document(ref), providers, DiscoverySettings(providers=[]))
    record = next(record for record in result.literature if record.role == "reference")
    assert record.resolution.status == "matched"
    assert record.metadata.title == "A scientific study"
    assert record.metadata.authors == ["Alice Smith"]
    assert record.metadata.year == "2020"
    assert record.extracted[0] == ref


def test_crossref_rate_limit_still_allows_model_planning_for_dnb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    def crossref_result(_reference: PaperMetadata) -> list[Candidate]:
        raise ValueError("Crossref HTTP 429")

    providers = providers_recording(
        calls,
        crossref_result,
        lambda provider, query: [candidate(query, provider=provider)] if query.title else [],
    )
    result = run_discovery(tmp_path, document(ref), providers, DiscoverySettings(providers=["dnb"]))
    record = next(record for record in result.literature if record.role == "reference")
    assert record.resolution.status == "matched"
    assert record.resolution.provider == "dnb"
    assert sum(provider == "crossref" and query.id == "r1" for provider, query in calls) >= 1
    assert sum(provider == "dnb" for provider, _ in calls) == 1


def test_missing_title_skips_inapplicable_adapters(
    tmp_path: Path,
) -> None:
    calls = []
    ref = reference(title=None, authors=[], year=None, raw="Smith (2020). A scientific study.")
    result = run_discovery(
        tmp_path,
        document(ref),
        providers_recording(calls),
        DiscoverySettings(),
    )
    assert [provider for provider, query in calls if query.id == "r1"] == ["crossref"]
    trace = next(trace for trace in result.report.searches if trace.reference_id == "r1")
    assert {query.provider for query in trace.queries if query.status == "skipped"} == {
        "dnb",
        "openalex",
        "openlibrary",
    }


def test_model_plan_rejects_invented_bibliographic_fields() -> None:
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


def test_model_plan_rejects_partial_word_author_and_year_fabrication() -> None:
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


def test_failed_model_planning_is_repeated_for_identical_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fail(*_args: object, **_kwargs: object) -> Never:
        calls.append(True)
        raise RuntimeError("Private upstream failure detail")

    monkeypatch.setattr(planning.structured_generation, "generate", fail)
    first, second = DiscoveryReport(), DiscoveryReport()
    for report in (first, second):
        plan = planning.plan_reference_queries(
            [ReferenceQueryEvidence(reference=reference(), candidates=[])],
            report,
            ModelConfiguration(),
            lambda: False,
        )
        assert plan.queries == []
        assert "Private upstream" not in report.model_dump_json()
    assert len(calls) == 2


def test_optional_unpaywall_runs_for_confirmed_doi(tmp_path: Path) -> None:
    calls = []
    providers = providers_recording(calls, lambda ref: [candidate(ref, doi="10.1234/work")])

    def access(ref: PaperMetadata, *_args: object) -> list[Candidate]:
        calls.append(("unpaywall", ref.model_copy(deep=True)))
        return [candidate(ref, provider="unpaywall", open_access_url="https://example.org/open")]

    providers["unpaywall"] = access
    run_discovery(
        tmp_path,
        document(reference()),
        providers,
        DiscoverySettings(find_open_access=True),
    )
    assert sum(provider == "unpaywall" for provider, _ in calls) == 1


def test_unpaywall_skips_unconfirmed_dois_absent_dois_and_existing_links(tmp_path: Path) -> None:
    calls = []
    refs = [
        reference("unmatched", title="Unmatched title", doi="10.1234/unconfirmed"),
        reference("no-doi", title="No DOI"),
        reference("has-link", title="Known access location"),
    ]

    def found(ref: PaperMetadata) -> list[Candidate]:
        assert isinstance(ref, PaperReference)
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
        DiscoverySettings(find_open_access=True),
    )
    assert not any(
        trace.trigger == "Missing open-access location" for trace in result.report.searches
    )


def test_complete_exact_isbn_match_skips_crossref_and_remaining_providers(tmp_path: Path) -> None:
    calls = []
    ref = reference(title=None, authors=[], year=None, raw="ISBN 3-593-37978-3")
    providers = providers_recording(calls)

    def dnb(query: PaperMetadata, *_args: object) -> list[Candidate]:
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


@pytest.mark.parametrize(
    "settings",
    [
        {"providers": ["dnb", "dnb"]},
        {"required_fields": []},
        {"required_fields": ["title", "title"]},
    ],
)
def test_discovery_settings_reject_invalid_search_requirements(settings: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        DiscoverySettings.model_validate(settings)


@pytest.mark.parametrize("error_type", [KeyError, TypeError, InterruptedError])
def test_provider_defects_and_cancellation_propagate(error_type: type[Exception]) -> None:
    def fail(*_args: object) -> Never:
        raise error_type("provider stopped")

    session = reference_search.ReferenceSearchSession(
        settings=DiscoverySettings(),
        report=DiscoveryReport(),
        cancelled=lambda: False,
        providers={"crossref": fail},
    )
    trace = ReferenceSearch(reference_id="r1", trigger="Unmatched")

    with pytest.raises(error_type):
        session.search("crossref", reference(), trace)


def test_planning_bounds_model_input_without_discarding_collected_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    packets = []

    def plan(
        _instructions: str, packet: str, *_args: object, **_kwargs: object
    ) -> planning.ReferenceQueries:
        packets.append(json.loads(packet))
        return planning.ReferenceQueries()

    def lookup(ref: PaperMetadata, *_args: object) -> list[Candidate]:
        return [candidate(ref, identifier=f"work-{index}", year="1900") for index in range(7)]

    monkeypatch.setattr(planning.structured_generation, "generate", plan)
    result = run_discovery(
        tmp_path,
        document(*(reference(f"r{index}") for index in range(55))),
        {"crossref": lookup},
        DiscoverySettings(providers=[]),
    )

    assert len(packets) == 1
    assert len(packets[0]) == 50
    assert all(len(entry["candidates"]) == 6 for entry in packets[0])
    assert all(len(record.resolution.candidates) == 7 for record in result.literature)
    assert len(result.literature) == 56
