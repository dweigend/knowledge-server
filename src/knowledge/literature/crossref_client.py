"""Retrieve bounded Crossref candidates for literature resolution.

The client normalizes metadata and DOI values while leaving identity decisions
to the resolver.
"""

import re
from collections.abc import Callable
from typing import Final
from urllib.parse import quote, urlencode

from knowledge.literature import crossref_models, literature_models, structured_paper_models
from knowledge.literature.provider_http import MAX_CANDIDATES, request_model

API_URL: Final[str] = "https://api.crossref.org/works"


def normalize_doi(doi: str | None) -> str | None:
    """Normalize DOI wrappers while retaining the identifier's actual suffix."""
    cleaned = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi or "", flags=re.I)
    cleaned = cleaned.strip().lower()
    return cleaned if re.fullmatch(r"10\.\d{4,9}/\S+", cleaned) else None


def lookup_crossref(
    reference: structured_paper_models.PaperMetadata,
    timeout_seconds: float,
    cancelled: Callable[[], bool],
) -> list[literature_models.Candidate]:
    """Look up an exact DOI or retrieve at most three bibliographic candidates."""
    doi = normalize_doi(reference.doi)
    url = lookup_url(reference, doi)
    if url is None:
        return []
    method = "doi" if doi else "bibliographic"
    response = request_model(url, crossref_models.Response, timeout_seconds, cancelled)
    if response is None:
        return []
    message = response.message
    if (method == "doi") != isinstance(message, crossref_models.Work):
        raise ValueError("Crossref returned an unexpected response type")
    entries = [message] if isinstance(message, crossref_models.Work) else message.items
    return [
        literature_models.Candidate(
            metadata=parse_metadata(entry),
            provider="crossref",
            provider_id=entry.doi,
            method=method,
        )
        for entry in entries[:MAX_CANDIDATES]
    ]


def lookup_url(reference: structured_paper_models.PaperMetadata, doi: str | None) -> str | None:
    """Build an exact identifier query or retain the original bibliographic evidence."""
    if doi:
        return API_URL + "/" + quote(doi, safe="")
    raw = reference.raw if isinstance(reference, structured_paper_models.PaperReference) else None
    query = raw or " ".join(filter(None, [reference.title, *reference.authors, reference.year]))
    if not query:
        return None
    return API_URL + "?" + urlencode({"query.bibliographic": query[:2000], "rows": MAX_CANDIDATES})


def parse_metadata(entry: crossref_models.Metadata | dict) -> literature_models.LiteratureMetadata:
    """Normalize deposited Crossref metadata without filling absent fields."""
    metadata = crossref_models.Metadata.model_validate(entry)
    return literature_models.LiteratureMetadata(
        title=next(iter(metadata.title), None),
        authors=[
            " ".join(filter(None, [author.given, author.family])) or author.name
            for author in metadata.author
        ],
        year=publication_year(metadata),
        venue=next(iter(metadata.container_title), None),
        doi=normalize_doi(metadata.doi),
        publisher=metadata.publisher,
        volume=metadata.volume,
        issue=metadata.issue,
        pages=metadata.page,
        work_type=metadata.type,
        url=metadata.url,
        isbn=metadata.isbn,
        issn=metadata.issn,
    )


def publication_year(entry: crossref_models.Metadata | dict) -> str | None:
    """Select a supplied publication year, excluding metadata deposit timestamps."""
    metadata = crossref_models.Metadata.model_validate(entry)
    dates = (
        metadata.published,
        metadata.published_print,
        metadata.published_online,
        metadata.issued,
    )
    for date in dates:
        if not date.date_parts or not date.date_parts[0]:
            continue
        year = date.date_parts[0][0]
        if type(year) is int and 1000 <= year <= 9999:
            return str(year)
    return None
