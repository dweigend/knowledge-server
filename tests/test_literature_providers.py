import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from typing import BinaryIO
from urllib.parse import parse_qs, urlsplit

import pytest

from knowledge.literature import (
    dnb_client,
    google_books_client,
    openalex_client,
    openlibrary_client,
    provider_http,
    semantic_scholar_client,
    unpaywall_client,
)
from knowledge.literature.literature_resolution import Lookup
from knowledge.literature.structured_paper_models import PaperMetadata, PaperReference


@pytest.fixture
def reference() -> PaperMetadata:
    return PaperMetadata(title="Nachhaltigkeit", authors=["Armin Grunwald"], year="2006")


def mock_response(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> list[tuple[str, Mapping[str, str] | None]]:
    requests = []

    def request(
        url: str,
        timeout: float,
        cancelled: Callable[[], bool],
        *,
        accept: str = "application/json",
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        requests.append((url, headers))
        return json.dumps(payload).encode()

    monkeypatch.setattr(provider_http, "request_bytes", request)
    return requests


def test_openalex_exact_doi_uses_bearer_key_and_preserves_missing_fields(
    monkeypatch: pytest.MonkeyPatch, reference: PaperMetadata
) -> None:
    monkeypatch.setenv("KNOWLEDGE_OPENALEX_API_KEY", "private-test-key")
    requests = mock_response(
        monkeypatch,
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1234/book",
            "title": "Nachhaltigkeit",
            "publication_year": 2006,
            "authorships": [{"author": {"display_name": "Armin Grunwald"}}],
            "type": "book",
            "primary_location": None,
        },
    )
    reference.doi = "10.1234/BOOK"
    result = openalex_client.lookup_openalex(reference, 2, lambda: False)[0]
    assert result.method == "doi"
    assert result.metadata.doi == "10.1234/book"
    assert result.metadata.venue is None
    assert result.metadata.authors == ["Armin Grunwald"]
    assert "private-test-key" not in requests[0][0]
    assert requests[0][1] == {"Authorization": "Bearer private-test-key"}


def test_openalex_search_is_bounded_and_uses_year_filter(
    monkeypatch: pytest.MonkeyPatch, reference: PaperMetadata
) -> None:
    requests = mock_response(monkeypatch, {"results": [{"id": f"W{index}"} for index in range(8)]})
    candidates = openalex_client.lookup_openalex(reference, 2, lambda: False)
    assert len(candidates) == 3
    assert parse_qs(urlsplit(requests[0][0]).query)["filter"] == ["publication_year:2006"]


def marc_response(fields: str) -> bytes:
    return (
        f'<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">'
        f'<records><record><recordData><record xmlns="http://www.loc.gov/MARC21/slim">'
        f'<leader>00000nam a2200000 c 4500</leader><controlfield tag="001">123</controlfield>'
        f"{fields}</record></recordData></record></records></searchRetrieveResponse>"
    ).encode()


def test_dnb_parses_actual_marc_fields_without_treating_editors_as_authors() -> None:
    response = marc_response("""
      <datafield tag="245"><subfield code="a">Nachhaltigkeit</subfield></datafield>
      <datafield tag="100"><subfield code="a">Grunwald, Armin</subfield>
        <subfield code="4">aut</subfield></datafield>
      <datafield tag="700"><subfield code="a">Other, Editor</subfield>
        <subfield code="4">edt</subfield></datafield>
      <datafield tag="264"><subfield code="b">Campus</subfield>
        <subfield code="c">[2006]</subfield></datafield>
      <datafield tag="020"><subfield code="a">9783593379784</subfield></datafield>
      <datafield tag="024"><subfield code="a">10.1234/BOOK</subfield>
        <subfield code="2">doi</subfield></datafield>
    """)
    candidate = dnb_client.parse_candidates(response)[0]
    assert candidate.provider_id == "123"
    assert candidate.metadata.authors == ["Armin Grunwald"]
    assert candidate.metadata.year == "2006"
    assert candidate.metadata.publisher == "Campus"
    assert candidate.metadata.isbn == ["9783593379784"]
    assert candidate.metadata.doi == "10.1234/book"
    assert candidate.metadata.work_type == "book"


def test_dnb_query_escapes_cql_and_never_searches_venue_as_title(
    monkeypatch: pytest.MonkeyPatch, reference: PaperMetadata
) -> None:
    requests = []

    def request(url: str, *_args: object, **_kwargs: object) -> bytes | None:
        requests.append(url)
        return None

    monkeypatch.setattr(dnb_client, "request_bytes", request)
    reference.title = 'A "title"'
    reference.venue = "A containing book"
    assert dnb_client.lookup_dnb(reference, 2, lambda: False) == []
    query = parse_qs(urlsplit(requests[0]).query)
    assert query["query"] == ['tit="A \\"title\\"" and per="grunwald" and jhr=2006']
    assert query["maximumRecords"] == ["3"]
    assert "containing" not in query["query"][0]


@pytest.mark.parametrize(
    "author, surname",
    [
        ("Grunwald A", "grunwald"),
        ("Gethmann C F", "gethmann"),
        ("Grunwald, Armin", "grunwald"),
    ],
)
def test_dnb_uses_author_surname_instead_of_trailing_initial(
    monkeypatch: pytest.MonkeyPatch, reference: PaperMetadata, author: str, surname: str
) -> None:
    requests = []

    def request(url: str, *_args: object, **_kwargs: object) -> bytes | None:
        requests.append(url)
        return None

    monkeypatch.setattr(dnb_client, "request_bytes", request)
    reference.authors = [author]
    dnb_client.lookup_dnb(reference, 2, lambda: False)
    query = parse_qs(urlsplit(requests[0]).query)["query"][0]
    assert f'per="{surname}"' in query


def test_dnb_chapter_retains_container_without_inheriting_its_title() -> None:
    response = marc_response("""
      <datafield tag="245"><subfield code="a">A chapter</subfield></datafield>
      <datafield tag="773"><subfield code="t">A book</subfield></datafield>
    """)
    metadata = dnb_client.parse_candidates(response)[0].metadata
    assert metadata.title == "A chapter"
    assert metadata.venue == "A book"
    assert metadata.work_type == "book-chapter"


@pytest.mark.parametrize(
    "response, message",
    [
        (b"<invalid", "invalid XML"),
        (b"<html>Upstream maintenance</html>", "unexpected XML"),
        (b'<!DOCTYPE x [<!ENTITY e "secret">]><x>&e;</x>', "forbidden declarations"),
        (
            b'<diagnostics xmlns="http://www.loc.gov/zing/srw/diagnostic/"><diagnostic/></diagnostics>',
            "SRU diagnostic",
        ),
    ],
)
def test_dnb_rejects_malformed_responses(response: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        dnb_client.parse_candidates(response)


def test_openlibrary_does_not_merge_work_year_or_isbns_into_an_edition(
    monkeypatch: pytest.MonkeyPatch, reference: PaperMetadata
) -> None:
    mock_response(
        monkeypatch,
        {
            "docs": [
                {
                    "key": "/works/W1",
                    "title": "Nachhaltigkeit",
                    "author_name": ["Armin Grunwald"],
                    "first_publish_year": 2006,
                    "isbn": ["work-isbn"],
                    "editions": {"docs": [{"key": "/books/B1", "title": "Nachhaltigkeit"}]},
                }
            ]
        },
    )
    candidate = openlibrary_client.lookup_openlibrary(reference, 2, lambda: False)[0]
    assert candidate.provider_id == "/books/B1"
    assert candidate.metadata.year is None
    assert candidate.metadata.isbn == []


def test_openlibrary_work_only_cannot_confirm_a_specific_edition(
    monkeypatch: pytest.MonkeyPatch, reference: PaperMetadata
) -> None:
    mock_response(
        monkeypatch,
        {
            "docs": [
                {
                    "key": "/works/W1",
                    "title": "Nachhaltigkeit",
                    "author_name": ["Armin Grunwald"],
                    "first_publish_year": 2006,
                    "isbn": ["work-isbn"],
                }
            ]
        },
    )
    candidate = openlibrary_client.lookup_openlibrary(reference, 2, lambda: False)[0]
    assert candidate.metadata.work_type == "book-work"
    assert candidate.metadata.year is None
    assert candidate.metadata.isbn == []


def test_semantic_scholar_preserves_doi_and_publication_type(
    monkeypatch: pytest.MonkeyPatch, reference: PaperMetadata
) -> None:
    mock_response(
        monkeypatch,
        {
            "data": [
                {
                    "paperId": "paper-1",
                    "title": "Nachhaltigkeit",
                    "authors": [{"name": "Armin Grunwald"}],
                    "externalIds": {"DOI": "10.1234/BOOK"},
                    "year": 2006,
                    "publicationTypes": ["BookSection"],
                }
            ]
        },
    )
    candidate = semantic_scholar_client.lookup_semantic_scholar(reference, 2, lambda: False)[0]
    assert candidate.metadata.work_type == "book-chapter"
    assert candidate.metadata.doi == "10.1234/book"
    assert candidate.metadata.year == "2006"


def test_google_books_requires_key_and_retains_volume_identifiers(
    monkeypatch: pytest.MonkeyPatch, reference: PaperMetadata
) -> None:
    monkeypatch.delenv("KNOWLEDGE_GOOGLE_BOOKS_API_KEY", raising=False)
    requests = mock_response(
        monkeypatch,
        {
            "items": [
                {
                    "id": "v1",
                    "volumeInfo": {
                        "title": "Nachhaltigkeit",
                        "publishedDate": "2006-03-01",
                        "printType": "BOOK",
                        "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9783593379784"}],
                    },
                }
            ]
        },
    )
    assert google_books_client.lookup_google_books(reference, 2, lambda: False) == []
    assert requests == []
    monkeypatch.setenv("KNOWLEDGE_GOOGLE_BOOKS_API_KEY", "test-key")
    metadata = google_books_client.lookup_google_books(reference, 2, lambda: False)[0].metadata
    assert metadata.year == "2006"
    assert metadata.isbn == ["9783593379784"]


def test_unpaywall_requires_contact_and_exact_doi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KNOWLEDGE_UNPAYWALL_EMAIL", raising=False)
    requests = mock_response(monkeypatch, {"doi": "10.1234/other", "best_oa_location": None})
    assert unpaywall_client.lookup_unpaywall("10.1234/book", 2, lambda: False) is None
    assert requests == []
    monkeypatch.setenv("KNOWLEDGE_UNPAYWALL_EMAIL", "test@example.org")
    with pytest.raises(ValueError, match="different DOI"):
        unpaywall_client.lookup_unpaywall("10.1234/book", 2, lambda: False)


def test_unpaywall_returns_access_location_without_identity_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_UNPAYWALL_EMAIL", "test@example.org")
    mock_response(
        monkeypatch,
        {
            "doi": "10.1234/book",
            "best_oa_location": {
                "url": "https://example.org/article",
                "url_for_pdf": "https://example.org/article.pdf",
                "license": "cc-by",
                "version": "publishedVersion",
            },
        },
    )
    result = unpaywall_client.lookup_unpaywall("10.1234/book", 2, lambda: False)
    assert result and result.url_for_pdf == "https://example.org/article.pdf"


def test_unpaywall_rejects_unsafe_access_location(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_UNPAYWALL_EMAIL", "test@example.org")
    mock_response(
        monkeypatch,
        {
            "doi": "10.1234/book",
            "best_oa_location": {
                "url": "javascript:alert(1)",
            },
        },
    )
    with pytest.raises(ValueError, match="invalid access URL"):
        unpaywall_client.lookup_unpaywall("10.1234/book", 2, lambda: False)


def test_json_validation_errors_hide_response_contents(
    monkeypatch: pytest.MonkeyPatch, reference: PaperMetadata
) -> None:
    mock_response(monkeypatch, {"results": "private-secret-returned-by-upstream"})
    with pytest.raises(ValueError) as caught:
        openalex_client.lookup_openalex(reference, 2, lambda: False)
    assert "private-secret" not in str(caught.value)


def use_child_process(
    monkeypatch: pytest.MonkeyPatch, program: str
) -> list[subprocess.Popen[bytes]]:
    original_popen = subprocess.Popen
    processes = []

    def popen(
        arguments: list[str], *, stdin: BinaryIO, stdout: BinaryIO, stderr: int
    ) -> subprocess.Popen[bytes]:
        assert "private-key" not in " ".join(arguments)
        process = original_popen(
            [sys.executable, "-c", program], stdin=stdin, stdout=stdout, stderr=stderr
        )
        processes.append(process)
        return process

    monkeypatch.setattr(provider_http.subprocess, "Popen", popen)
    return processes


@pytest.mark.parametrize("status", ["404", "429", "503"])
def test_transport_reports_status_without_echoing_secret_body(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    use_child_process(monkeypatch, f"print('private-key\\n{status}', end='')")
    if status == "404":
        assert (
            provider_http.request_bytes("https://example.org?key=private-key", 2, lambda: False)
            is None
        )
    else:
        with pytest.raises(ValueError, match=f"HTTP {status}") as caught:
            provider_http.request_bytes("https://example.org?key=private-key", 2, lambda: False)
        assert "private-key" not in str(caught.value)


def test_transport_rejects_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    use_child_process(
        monkeypatch, f"print('x' * {provider_http.MAX_RESPONSE_BYTES + 1} + '\\n200', end='')"
    )
    with pytest.raises(ValueError, match="size limit"):
        provider_http.request_bytes("https://example.org", 2, lambda: False)


def test_transport_kills_timed_out_process(monkeypatch: pytest.MonkeyPatch) -> None:
    processes = use_child_process(monkeypatch, "import time; time.sleep(5)")
    with pytest.raises(TimeoutError):
        provider_http.request_bytes("https://example.org", 0.1, lambda: False)
    assert processes[0].poll() is not None


def test_transport_kills_running_process_when_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    processes = use_child_process(monkeypatch, "import time; time.sleep(5)")
    checks = iter([False, False, True])
    with pytest.raises(InterruptedError):
        provider_http.request_bytes("https://example.org", 2, lambda: next(checks))
    assert processes[0].poll() is not None


def test_transport_rejects_header_injection_before_starting_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes = use_child_process(monkeypatch, "raise AssertionError('must not run')")
    with pytest.raises(ValueError, match="control characters"):
        provider_http.request_bytes(
            "https://example.org",
            2,
            lambda: False,
            headers={"Authorization": "Bearer secret\nurl=other"},
        )
    assert processes == []


@pytest.mark.parametrize(
    "supplied, expected",
    [
        ("978-3-593-37978-4", "9783593379784"),
        ("ISBN-13: 978 3 593 37978 4", "9783593379784"),
        ("3-593-37978-3", "9783593379784"),
        ("0-8044-2957-X", "9780804429573"),
        ("9783593379785", None),
        ("3593379784", None),
        ("1111111111111", None),
        ("invalid identifier", None),
        (None, None),
    ],
)
def test_isbn_normalization_validates_checksums_and_canonicalizes_ten_digits(
    supplied: str | None, expected: str | None
) -> None:
    from knowledge.literature.bibliographic_identifiers import normalize_isbn

    assert normalize_isbn(supplied) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Grunwald. ISBN 3-593-37978-3.", "9783593379784"),
        ("Grunwald. ISBN-13: 978-3-593-37978-4.", "9783593379784"),
        ("Grunwald. 9783593379784.", "9783593379784"),
        ("Grunwald. 3593379783.", None),
        ("Grunwald. ISBN 9783593379785.", None),
        ("ISBN 3593379783; ISBN 9783593379784", "9783593379784"),
        ("ISBN 9783593379784; ISBN 9783593413990", None),
    ],
)
def test_isbn_extraction_requires_valid_literal_unambiguous_evidence(
    raw: str, expected: str | None
) -> None:
    from knowledge.literature.bibliographic_identifiers import extracted_isbn

    assert extracted_isbn(PaperReference(id="r1", raw=raw)) == expected


def test_isbn_extraction_reuses_valid_supplied_metadata() -> None:
    from knowledge.literature.bibliographic_identifiers import extracted_isbn
    from knowledge.literature.literature_models import LiteratureMetadata

    assert extracted_isbn(LiteratureMetadata(isbn=["3593379783"])) == "9783593379784"


def test_dnb_prefers_verified_isbn_query_without_title_or_author(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    requests = []

    def request(url: str, *_args: object, **_kwargs: object) -> bytes | None:
        requests.append(url)
        return marc_response("""
          <datafield tag="245"><subfield code="a">Nachhaltigkeit</subfield></datafield>
          <datafield tag="020"><subfield code="a">9783593379784</subfield></datafield>
        """)

    monkeypatch.setattr(dnb_client, "request_bytes", request)
    found = dnb_client.lookup_dnb(PaperReference(id="r1", raw="ISBN 3593379783"), 2, lambda: False)
    assert parse_qs(urlsplit(requests[0]).query)["query"] == ["num=9783593379784"]
    assert found[0].method == "isbn"
    assert found[0].metadata.isbn == ["9783593379784"]


def test_openlibrary_prefers_isbn_and_retains_only_edition_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    requests = mock_response(
        monkeypatch,
        {
            "docs": [
                {
                    "key": "/works/W1",
                    "title": "Nachhaltigkeit",
                    "isbn": ["unrelated-work-isbn"],
                    "editions": {
                        "docs": [
                            {"key": "/books/B1", "title": "Nachhaltigkeit", "isbn": ["3593379783"]}
                        ]
                    },
                }
            ]
        },
    )
    found = openlibrary_client.lookup_openlibrary(
        PaperReference(id="r1", raw="ISBN 3593379783"), 2, lambda: False
    )
    query = parse_qs(urlsplit(requests[0][0]).query)
    assert query["isbn"] == ["9783593379784"]
    assert "title" not in query and "author" not in query
    assert found[0].method == "isbn"
    assert found[0].metadata.isbn == ["3593379783"]


def test_google_books_prefers_isbn_and_leaves_identifier_verification_to_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    monkeypatch.setenv("KNOWLEDGE_GOOGLE_BOOKS_API_KEY", "test-key")
    requests = mock_response(
        monkeypatch,
        {
            "items": [
                {
                    "id": "v1",
                    "volumeInfo": {
                        "title": "A different book",
                        "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9783593413990"}],
                    },
                }
            ]
        },
    )
    found = google_books_client.lookup_google_books(
        PaperReference(id="r1", raw="ISBN 3593379783"), 2, lambda: False
    )
    assert parse_qs(urlsplit(requests[0][0]).query)["q"] == ["isbn:9783593379784"]
    assert found[0].method == "isbn"
    assert found[0].metadata.isbn == ["9783593413990"]


@pytest.mark.parametrize(
    "lookup",
    [
        dnb_client.lookup_dnb,
        openlibrary_client.lookup_openlibrary,
        google_books_client.lookup_google_books,
    ],
)
def test_invalid_isbn_without_title_does_not_trigger_book_lookup(
    monkeypatch: pytest.MonkeyPatch, lookup: Lookup
) -> None:

    monkeypatch.setenv("KNOWLEDGE_GOOGLE_BOOKS_API_KEY", "test-key")
    monkeypatch.setattr(
        dnb_client, "request_bytes", lambda *_a, **_k: pytest.fail("Unexpected request")
    )
    monkeypatch.setattr(
        provider_http, "request_bytes", lambda *_a, **_k: pytest.fail("Unexpected request")
    )
    assert lookup(PaperReference(id="r1", raw="ISBN 9783593379785"), 2, lambda: False) == []
