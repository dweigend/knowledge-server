from collections.abc import Callable, Iterable
from typing import Literal, Never

import pytest
from pydantic import BaseModel

from knowledge.literature.crossref_client import normalize_doi, parse_metadata
from knowledge.literature.literature_models import Candidate, LiteratureMetadata, LiteratureRecord
from knowledge.literature.literature_resolution import Lookup, enrich_paper
from knowledge.literature.structured_paper_models import (
    PaperCitation,
    PaperDocument,
    PaperMetadata,
    PaperReference,
)


def candidate(
    doi: str = "10.1234/work",
    method: Literal["doi", "isbn", "bibliographic"] = "bibliographic",
    **fields: object,
) -> Candidate:
    return Candidate(
        provider="crossref",
        provider_id=doi,
        method=method,
        metadata=LiteratureMetadata.model_validate(
            {
                "title": "A scientific paper",
                "authors": ["Alice Smith"],
                "year": "2020",
                "doi": doi,
                **fields,
            }
        ),
    )


def paper(
    references: Iterable[PaperReference] = (),
    citations: Iterable[PaperCitation] = (),
    **metadata: object,
) -> PaperDocument:
    return PaperDocument(
        markdown="# Test",
        provider="grobid",
        metadata=PaperMetadata.model_validate(metadata),
        references=list(references),
        citations=list(citations),
    )


def enrich(document: PaperDocument, lookup: Lookup) -> list[LiteratureRecord]:
    return enrich_paper(
        document, "a" * 64, timeout_seconds=10, cancelled=lambda: False, lookup=lookup
    )


def reference(identifier: str = "b1", **fields: object) -> PaperReference:
    return PaperReference.model_validate(
        {
            "id": identifier,
            "title": "A scientific paper",
            "authors": ["A. Smith"],
            "year": "2020",
            "raw": "Smith (2020) original reference",
            **fields,
        }
    )


def test_corroborated_duplicates_merge_preserving_originals_and_occurrences() -> None:
    document = paper(
        [reference(), reference("b2")],
        [
            PaperCitation(marker="[1,2]", target_ids=["b1", "b2"], coordinates="1,2,3,4,5"),
            PaperCitation(marker="Smith", target_ids=["b1"]),
        ],
    )
    records = enrich(document, lambda ref, *_: [candidate()] if ref.title else [])
    assert len(records) == 2
    record = records[1]
    assert record.id == "doi:10.1234/work"
    assert record.reference_ids == ["b1", "b2"]
    assert len(record.extracted) == 2
    assert record.extracted[0].raw == "Smith (2020) original reference"
    assert len(record.occurrences) == 2
    assert record.occurrences[0].citing_source_id == "sha256:" + "a" * 64
    assert record.metadata.authors == ["Alice Smith"]
    assert "venue" in record.missing_fields


def test_wrong_doi_title_is_not_accepted_or_used_for_deduplication() -> None:
    wrong = candidate(method="doi")
    wrong.metadata.title = "A completely different paper"
    records = enrich(
        paper([reference(doi="10.1234/work"), reference("b2", doi="10.1234/work")]),
        lambda *_: [wrong],
    )
    assert len(records) == 3
    assert records[1].resolution.status == "unmatched"
    assert records[1].metadata.authors == ["A. Smith"]


def test_doi_with_author_appended_to_extracted_title_is_corroborated() -> None:
    document = paper(title="A scientific paper Alice Smith", doi="https://doi.org/10.1234/work")
    record = enrich(document, lambda *_: [candidate(method="doi")])[0]
    assert record.resolution.status == "matched"
    assert record.source_sha256 == "a" * 64


@pytest.mark.parametrize("field,replacement", [("authors", ["Jones"]), ("year", "2019")])
def test_title_alone_is_insufficient_for_search_match(
    field: str, replacement: str | list[str]
) -> None:
    source = reference()
    setattr(source, field, replacement)
    record = enrich(paper([source]), lambda *_: [candidate()])[1]
    assert record.resolution.status == "unmatched"


def test_two_matching_candidates_require_review() -> None:
    record = enrich(paper([reference()]), lambda *_: [candidate(), candidate("10.1234/other")])[1]
    assert record.resolution.status == "ambiguous"
    assert record.metadata.doi is None
    assert len(record.resolution.candidates) == 2


def test_unresolved_markers_and_unknown_targets_are_not_discarded() -> None:
    document = paper(
        citations=[PaperCitation(marker="[?]"), PaperCitation(marker="X", target_ids=["missing"])]
    )
    records = enrich(document, lambda *_: [])
    assert len(records) == 3
    assert records[1].metadata.title is None
    assert records[1].occurrences[0].marker == "[?]"
    assert records[2].reference_ids == ["missing"]


def test_repeated_identical_requests_are_cached() -> None:
    calls = []

    def lookup(ref: PaperMetadata, *_: object) -> list[Candidate]:
        calls.append(ref.title)
        return []

    records = enrich(paper([reference(), reference("b2")]), lookup)
    assert len(records) == 3  # Unmatched title duplicates are not merged.
    assert calls == [None, "A scientific paper"]


def test_provider_failure_keeps_extracted_data_and_explicit_error() -> None:
    def fail(*_: object) -> Never:
        raise ValueError("Crossref returned HTTP 429")

    record = enrich(paper([reference()]), fail)[1]
    assert record.resolution.status == "error"
    assert "429" in record.resolution.message
    assert record.metadata.title == "A scientific paper"


def test_cancellation_is_not_downgraded_to_lookup_error() -> None:
    with pytest.raises(InterruptedError):
        enrich_paper(paper(), "a" * 64, timeout_seconds=1, cancelled=lambda: True)


def test_crossref_metadata_preserves_book_fields_and_missing_values() -> None:
    metadata = parse_metadata(
        {
            "DOI": "10.1234/X",
            "title": ["Book"],
            "ISBN": ["123"],
            "published": {"date-parts": [[1999]]},
            "type": "book",
            "publisher": "Publisher",
            "author": [{"name": "Institute"}],
        }
    )
    assert metadata.doi == "10.1234/x"
    assert metadata.authors == ["Institute"]
    assert metadata.year == "1999"
    assert metadata.isbn == ["123"]
    assert metadata.venue is None


def test_doi_normalization_does_not_strip_valid_suffix_punctuation() -> None:
    assert normalize_doi("doi:10.1234/ABC(1)") == "10.1234/abc(1)"
    assert normalize_doi("not a DOI") is None


def test_crossref_lookup_uses_encoded_exact_doi_and_bounded_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import knowledge.literature.crossref_client as crossref_client

    requests = []

    def request(
        url: str, response_type: type[BaseModel], timeout: float, cancelled: Callable[[], bool]
    ) -> BaseModel:
        requests.append(url)
        entry = {"DOI": "10.1234/work", "title": ["A scientific paper"]}
        return response_type.model_validate(
            {"message": entry if "/10." in url else {"items": [entry]}}
        )

    monkeypatch.setattr(crossref_client, "request_model", request)
    exact = crossref_client.lookup_crossref(reference(doi="10.1234/work"), 2, lambda: False)
    searched = crossref_client.lookup_crossref(reference(), 2, lambda: False)
    assert exact[0].method == "doi"
    assert requests[0].endswith("/10.1234%2Fwork")
    assert "query.bibliographic=" in requests[1] and "rows=3" in requests[1]
    assert searched[0].method == "bibliographic"


def test_exhausted_total_budget_marks_remaining_sources_without_new_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import knowledge.literature.literature_resolution as literature_resolution

    times = iter([0.0, 0.1, 11.0])
    monkeypatch.setattr(literature_resolution, "monotonic", lambda: next(times))
    calls = []

    def lookup(ref: PaperMetadata, *_: object) -> list[Candidate]:
        assert isinstance(ref, PaperReference)
        calls.append(ref.id)
        return []

    records = enrich(paper([reference()]), lookup)
    assert calls == ["__source__"]
    assert records[1].resolution.status == "error"
    assert "budget exhausted" in records[1].resolution.message


def test_rate_limit_stops_further_requests_in_the_same_run(monkeypatch: pytest.MonkeyPatch) -> None:
    import knowledge.literature.literature_resolution as literature_resolution

    calls = []

    def limited(ref: PaperMetadata, *_: object) -> list[Candidate]:
        assert isinstance(ref, PaperReference)
        calls.append(ref.id)
        raise ValueError("Crossref returned HTTP 429")

    monkeypatch.setattr(literature_resolution, "lookup_crossref", limited)
    records = enrich_paper(
        paper([reference()]), "a" * 64, timeout_seconds=10, cancelled=lambda: False
    )
    assert calls == ["__source__"]
    assert all(record.resolution.status == "error" for record in records)


def test_identical_repeated_markers_remain_distinct_occurrences() -> None:
    marker = PaperCitation(marker="Smith", target_ids=["b1"])
    records = enrich(paper([reference()], [marker, marker]), lambda *_: [candidate()])
    assert [edge.occurrence_index for edge in records[1].occurrences] == [1, 2]


def test_duplicate_reference_ids_produce_ambiguous_stub_instead_of_false_edge() -> None:
    document = paper(
        [reference(), PaperReference(id="b1", title="Different paper")],
        [PaperCitation(marker="Smith", target_ids=["b1"])],
    )
    records = enrich(document, lambda *_: [])
    assert len(records) == 4
    assert records[1].occurrences == records[2].occurrences == []
    assert records[3].resolution.status == "ambiguous"
    assert records[3].metadata.title is None
    assert records[3].occurrences[0].marker == "Smith"


def test_publication_year_uses_issued_but_never_deposit_timestamp() -> None:
    assert parse_metadata({"issued": {"date-parts": [[2009]]}}).year == "2009"
    assert (
        parse_metadata(
            {"issued": {"date-parts": [[None]]}, "created": {"date-parts": [[2009]]}}
        ).year
        is None
    )


def test_missing_title_requires_distinctive_exact_raw_title_with_author_and_year() -> None:
    ref = PaperReference(
        id="b1", authors=["A. Smith"], year="2020", raw="Smith (2020). A scientific paper. Journal."
    )
    record = enrich(paper([ref]), lambda *_: [candidate()])[1]
    # A scientific paper is too short to be a distinctive raw title match.
    assert record.resolution.status == "unmatched"
    external = candidate()
    external.metadata.title = "Foresight Knowledge Assessment"
    ref.raw = "Smith (2020). Foresight Knowledge Assessment. Journal."
    assert enrich(paper([ref]), lambda *_: [external])[1].resolution.status == "matched"
    ref.year = "2021"
    assert enrich(paper([ref]), lambda *_: [external])[1].resolution.status == "unmatched"
    ref.year = "2020"
    ref.raw = "Smith (2020). A different title. Journal."
    assert enrich(paper([ref]), lambda *_: [external])[1].resolution.status == "unmatched"


def test_bibliographic_query_uses_raw_reference_when_title_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from urllib.parse import parse_qs, urlsplit

    import knowledge.literature.crossref_client as crossref_client

    urls = []

    def request(url: str, response_type: type[BaseModel], *_: object) -> BaseModel:
        urls.append(url)
        return response_type.model_validate({"message": {"items": []}})

    monkeypatch.setattr(crossref_client, "request_model", request)
    ref = PaperReference(id="b1", raw="Smith (2020). Full original reference.")
    crossref_client.lookup_crossref(ref, 2, lambda: False)
    assert parse_qs(urlsplit(urls[0]).query)["query.bibliographic"] == [ref.raw]


@pytest.mark.parametrize(
    "extracted_author, catalog_author",
    [
        ("Grunwald A", "Armin Grunwald"),
        ("Gethmann C F", "Carl Friedrich Gethmann"),
        ("Grunwald, A.", "Armin Grunwald"),
    ],
)
def test_author_surnames_match_with_trailing_initials(
    extracted_author: str, catalog_author: str
) -> None:
    from knowledge.literature.literature_resolution import candidate_matches

    original = reference().model_copy(update={"authors": [extracted_author]})
    found = candidate()
    found.metadata.authors = [catalog_author]
    assert candidate_matches(original, found)


def test_matching_given_name_does_not_confirm_different_author_surname() -> None:
    from knowledge.literature.literature_resolution import candidate_matches

    original = reference().model_copy(update={"authors": ["Alice Smith"]})
    found = candidate()
    found.metadata.authors = ["Alice Jones"]
    assert not candidate_matches(original, found)


@pytest.mark.parametrize(
    "source_title, candidate_title, returned_isbn, expected",
    [
        (None, "Nachhaltigkeit", "9783593379784", True),
        ("Nachhaltigkeit", "Nachhaltigkeit", "9783593413990", False),
        ("Different book", "Nachhaltigkeit", "9783593379784", False),
    ],
)
def test_exact_isbn_requires_matching_identifier_and_no_title_conflict(
    source_title: str | None, candidate_title: str, returned_isbn: str, expected: bool
) -> None:
    from knowledge.literature.literature_resolution import candidate_matches

    original = PaperReference(id="isbn", title=source_title, raw="ISBN 3-593-37978-3")
    found = Candidate(
        provider="dnb",
        provider_id="edition-one",
        method="isbn",
        metadata=LiteratureMetadata(title=candidate_title, isbn=[returned_isbn]),
    )
    assert candidate_matches(original, found) is expected
