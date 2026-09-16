"""Retrieve bounded Semantic Scholar Academic Graph candidates."""

import os
from collections.abc import Callable
from urllib.parse import quote, urlencode

from pydantic import BaseModel, Field

from knowledge.literature.crossref_client import normalize_doi
from knowledge.literature.literature_models import Candidate, LiteratureMetadata
from knowledge.literature.provider_http import MAX_CANDIDATES, request_model
from knowledge.literature.structured_paper_models import PaperMetadata

API_URL = "https://api.semanticscholar.org/graph/v1/paper"
FIELDS = "title,authors,year,venue,url,externalIds,publicationTypes"


class _Author(BaseModel):
    name: str


class _Identifiers(BaseModel):
    doi: str | None = Field(default=None, alias="DOI")


class _Paper(BaseModel):
    paper_id: str = Field(alias="paperId")
    title: str | None = None
    authors: list[_Author] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    url: str | None = None
    external_ids: _Identifiers | None = Field(default=None, alias="externalIds")
    publication_types: list[str] | None = Field(default=None, alias="publicationTypes")


class _Search(BaseModel):
    data: list[_Paper]


def lookup_semantic_scholar(
    reference: PaperMetadata, timeout_seconds: float, cancelled: Callable[[], bool]
) -> list[Candidate]:
    """Look up a DOI or search a title with an optional configured API key."""
    doi = normalize_doi(reference.doi)
    if not doi and not reference.title:
        return []
    key = os.environ.get("KNOWLEDGE_SEMANTIC_SCHOLAR_API_KEY")
    headers = {"x-api-key": key} if key else {}
    if doi:
        response = request_model(
            API_URL + "/" + quote("DOI:" + doi, safe="") + "?" + urlencode({"fields": FIELDS}),
            _Paper,
            timeout_seconds,
            cancelled,
            headers=headers,
        )
        papers = [response] if response else []
    else:
        query = {
            "query": (reference.title or "")[:500],
            "limit": str(MAX_CANDIDATES),
            "fields": FIELDS,
        }
        response = request_model(
            API_URL + "/search?" + urlencode(query),
            _Search,
            timeout_seconds,
            cancelled,
            headers=headers,
        )
        papers = response.data if response else []
    return [_candidate(paper, bool(doi)) for paper in papers[:MAX_CANDIDATES]]


def _candidate(paper: _Paper, exact_doi: bool) -> Candidate:
    work_types = {
        "JournalArticle": "journal-article",
        "Book": "book",
        "BookSection": "book-chapter",
    }
    supplied_types = [
        work_types[name] for name in paper.publication_types or [] if name in work_types
    ]
    return Candidate(
        provider="semantic_scholar",
        provider_id=paper.paper_id,
        method="doi" if exact_doi else "bibliographic",
        metadata=LiteratureMetadata(
            title=paper.title,
            authors=[author.name for author in paper.authors],
            year=str(paper.year) if paper.year else None,
            venue=paper.venue or None,
            doi=normalize_doi(paper.external_ids.doi) if paper.external_ids else None,
            work_type=next(iter(supplied_types), None),
            url=paper.url,
        ),
    )
