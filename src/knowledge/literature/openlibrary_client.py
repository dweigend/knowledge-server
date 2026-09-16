"""Retrieve Open Library book candidates without mixing edition metadata."""

import re
from collections.abc import Callable
from typing import Final
from urllib.parse import urlencode

from pydantic import BaseModel, Field, TypeAdapter

from knowledge.literature.bibliographic_identifiers import extracted_isbn
from knowledge.literature.literature_models import Candidate, LiteratureMetadata
from knowledge.literature.provider_http import MAX_CANDIDATES, request_model
from knowledge.literature.structured_paper_models import PaperMetadata

API_URL: Final[str] = "https://openlibrary.org/search.json"


class _Edition(BaseModel):
    key: str
    title: str | None = None
    publish_date: list[str] = Field(default_factory=list)
    publisher: list[str] = Field(default_factory=list)
    isbn: list[str] = Field(default_factory=list)


class _Editions(BaseModel):
    docs: list[_Edition] = Field(default_factory=list)


class _Work(BaseModel):
    key: str
    title: str | None = None
    author_name: list[str] = Field(default_factory=list)
    editions: _Editions | None = None


def lookup_openlibrary(
    reference: PaperMetadata, timeout_seconds: float, cancelled: Callable[[], bool]
) -> list[Candidate]:
    """Search books while retaining each returned edition as a distinct candidate."""
    isbn = extracted_isbn(reference)
    if not reference.title and not isbn:
        return []
    query = {
        "limit": str(MAX_CANDIDATES),
        "fields": (
            "key,title,author_name,editions,editions.key,editions.title,"
            "editions.publish_date,editions.publisher,editions.isbn"
        ),
    }
    query["isbn" if isbn else "title"] = isbn or (reference.title or "")[:500]
    if reference.authors and not isbn:
        query["author"] = reference.authors[0][:200]
    works = request_model(
        API_URL + "?" + urlencode(query),
        TypeAdapter(list[_Work]),
        timeout_seconds,
        cancelled,
        collection_key="docs",
    )
    return [_candidate(work, bool(isbn)) for work in (works or [])[:MAX_CANDIDATES]]


def _candidate(work: _Work, exact_isbn: bool = False) -> Candidate:
    edition = next(iter(work.editions.docs), None) if work.editions else None
    years = re.findall(r"\b[12]\d{3}\b", " ".join(edition.publish_date)) if edition else []
    identifier = edition.key if edition else work.key
    return Candidate(
        provider="openlibrary",
        provider_id=identifier,
        method="isbn" if exact_isbn else "bibliographic",
        metadata=LiteratureMetadata(
            title=edition.title if edition else work.title,
            authors=work.author_name,
            year=years[0] if len(set(years)) == 1 else None,
            publisher=next(iter(edition.publisher), None) if edition else None,
            isbn=edition.isbn if edition else [],
            work_type="book" if edition else "book-work",
            url="https://openlibrary.org" + identifier,
        ),
    )
