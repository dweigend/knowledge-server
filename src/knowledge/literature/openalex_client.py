"""Retrieve OpenAlex work candidates using its public works API."""

import os
from collections.abc import Callable
from typing import Final
from urllib.parse import quote, urlencode

from pydantic import BaseModel, Field, TypeAdapter

from knowledge.literature.crossref_client import normalize_doi
from knowledge.literature.literature_models import Candidate, LiteratureMetadata
from knowledge.literature.provider_http import MAX_CANDIDATES, request_model
from knowledge.literature.structured_paper_models import PaperMetadata

API_URL: Final[str] = "https://api.openalex.org/works"


class _Author(BaseModel):
    display_name: str | None = None


class _Authorship(BaseModel):
    author: _Author


class _Source(BaseModel):
    display_name: str | None = None
    issn: list[str] | None = None


class _Location(BaseModel):
    source: _Source | None = None
    landing_page_url: str | None = None


class _Work(BaseModel):
    id: str
    title: str | None = None
    doi: str | None = None
    publication_year: int | None = None
    authorships: list[_Authorship] = Field(default_factory=list)
    primary_location: _Location | None = None
    type: str | None = None


def lookup_openalex(
    reference: PaperMetadata, timeout_seconds: float, cancelled: Callable[[], bool]
) -> list[Candidate]:
    """Retrieve at most three works; leave bibliographic identity checks to the resolver."""
    doi = normalize_doi(reference.doi)
    if not doi and not reference.title:
        return []
    key = os.environ.get("KNOWLEDGE_OPENALEX_API_KEY")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if doi:
        response = request_model(
            API_URL + "/" + quote("https://doi.org/" + doi, safe=""),
            _Work,
            timeout_seconds,
            cancelled,
            headers=headers,
        )
        works = [response] if response else []
    else:
        query = {"search": (reference.title or "")[:500], "per-page": str(MAX_CANDIDATES)}
        if reference.year and reference.year.isdigit():
            query["filter"] = "publication_year:" + reference.year
        works = request_model(
            API_URL + "?" + urlencode(query),
            TypeAdapter(list[_Work]),
            timeout_seconds,
            cancelled,
            headers=headers,
            collection_key="results",
        )
    return [_candidate(work, bool(doi)) for work in (works or [])[:MAX_CANDIDATES]]


def _candidate(work: _Work, exact_doi: bool) -> Candidate:
    source = work.primary_location.source if work.primary_location else None
    return Candidate(
        provider="openalex",
        provider_id=work.id,
        method="doi" if exact_doi else "bibliographic",
        metadata=LiteratureMetadata(
            title=work.title,
            authors=[
                entry.author.display_name for entry in work.authorships if entry.author.display_name
            ],
            year=str(work.publication_year) if work.publication_year else None,
            doi=normalize_doi(work.doi),
            venue=source.display_name if source else None,
            issn=(source.issn or []) if source else [],
            work_type=work.type,
            url=work.primary_location.landing_page_url if work.primary_location else None,
        ),
    )
