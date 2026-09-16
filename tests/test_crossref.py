import pytest

from knowledge.literature import crossref_client, provider_http
from knowledge.literature.structured_paper_models import PaperReference


@pytest.mark.parametrize("year", [True, False, None, "2009", 2009.0, 999, 10000])
def test_invalid_year_preserves_fallback_precedence(year):
    metadata = crossref_client.parse_metadata(
        {
            "published": {"date-parts": [[year]]},
            "published-print": {"date-parts": [[2010]]},
            "published-online": {"date-parts": [[2011]]},
            "issued": {"date-parts": [[2012]]},
        }
    )
    assert metadata.year == "2010"


def test_crossref_preserves_deposited_whitespace_and_author_names():
    metadata = crossref_client.parse_metadata(
        {
            "title": ["  Original title  "],
            "author": [{"given": " A ", "family": " Smith "}, {"name": " Institute "}],
            "container-title": [" Journal "],
        }
    )
    assert metadata.title == "  Original title  "
    assert metadata.authors == [" A   Smith ", " Institute "]
    assert metadata.venue == " Journal "


@pytest.mark.parametrize(
    "body",
    [
        b'{"message": {}}',
        b'{"message": {"items": [{"title": ["No DOI"]}]}}',
        b'{"message": {"DOI": "10.1234/x", "author": [null]}}',
        b"not json",
    ],
)
def test_malformed_external_response_raises_redacted_validation_error(monkeypatch, body):
    monkeypatch.setattr(provider_http, "request_bytes", lambda *args, **kwargs: body)
    with pytest.raises(ValueError, match="Provider returned invalid bibliographic JSON"):
        crossref_client.lookup_crossref(PaperReference(id="b1", title="Title"), 1, lambda: False)


def test_shared_transport_404_produces_no_candidates(monkeypatch):
    monkeypatch.setattr(provider_http, "request_bytes", lambda *args, **kwargs: None)
    assert (
        crossref_client.lookup_crossref(PaperReference(id="b1", doi="10.1234/x"), 1, lambda: False)
        == []
    )


def test_search_candidates_are_bounded_even_when_provider_returns_more(monkeypatch):
    body = (
        b'{"message": {"items": [{"DOI": "10.1234/1"}, {"DOI": "10.1234/2"}, '
        b'{"DOI": "10.1234/3"}, {"DOI": "10.1234/4"}]}}'
    )
    monkeypatch.setattr(provider_http, "request_bytes", lambda *args, **kwargs: body)
    candidates = crossref_client.lookup_crossref(
        PaperReference(id="b1", title="Title"), 1, lambda: False
    )
    assert [candidate.provider_id for candidate in candidates] == [
        "10.1234/1",
        "10.1234/2",
        "10.1234/3",
    ]


@pytest.mark.parametrize(
    "error", [InterruptedError(), TimeoutError(), ValueError("Provider returned HTTP 429")]
)
def test_transport_failures_propagate_without_a_second_error_layer(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(provider_http, "request_bytes", fail)
    with pytest.raises(type(error)) as captured:
        crossref_client.lookup_crossref(PaperReference(id="b1", title="Title"), 1, lambda: False)
    assert captured.value is error
