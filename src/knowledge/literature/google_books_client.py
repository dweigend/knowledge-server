"""Retrieve Google Books volumes when an API key is configured."""

import os
import re
from collections.abc import Callable
from typing import Final
from urllib.parse import urlencode

from pydantic import BaseModel, Field, TypeAdapter

from knowledge.literature.bibliographic_identifiers import extracted_isbn
from knowledge.literature.literature_models import Candidate, LiteratureMetadata
from knowledge.literature.provider_http import MAX_CANDIDATES, request_model
from knowledge.literature.structured_paper_models import PaperMetadata

API_URL: Final[str] = "https://www.googleapis.com/books/v1/volumes"


class _Identifier(BaseModel):
    type: str
    identifier: str


class _VolumeInfo(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    publisher: str | None = None
    published_date: str | None = Field(default=None, alias="publishedDate")
    industry_identifiers: list[_Identifier] = Field(
        default_factory=list, alias="industryIdentifiers"
    )
    info_link: str | None = Field(default=None, alias="infoLink")
    print_type: str | None = Field(default=None, alias="printType")


class _Volume(BaseModel):
    id: str
    volume_info: _VolumeInfo = Field(alias="volumeInfo")


def lookup_google_books(
    reference: PaperMetadata, timeout_seconds: float, cancelled: Callable[[], bool]
) -> list[Candidate]:
    """Look up ISBN or title and author when the required Google API key is present."""
    key = os.environ.get("KNOWLEDGE_GOOGLE_BOOKS_API_KEY")
    isbn = extracted_isbn(reference)
    if not key or (not reference.title and not isbn):
        return []
    query = (
        "isbn:" + isbn
        if isbn
        else 'intitle:"' + (reference.title or "").replace('"', " ")[:500] + '"'
    )
    if reference.authors and not isbn:
        query += ' inauthor:"' + reference.authors[0].replace('"', " ")[:200] + '"'
    url = API_URL + "?" + urlencode({"q": query, "maxResults": MAX_CANDIDATES, "key": key})
    volumes = request_model(
        url,
        TypeAdapter(list[_Volume]),
        timeout_seconds,
        cancelled,
        allow_missing_collection=True,
        collection_key="items",
    )
    return [_candidate(volume, bool(isbn)) for volume in (volumes or [])[:MAX_CANDIDATES]]


def _candidate(volume: _Volume, exact_isbn: bool = False) -> Candidate:
    info = volume.volume_info
    year = re.match(r"([12]\d{3})(?:-|$)", info.published_date or "")
    return Candidate(
        provider="google_books",
        provider_id=volume.id,
        method="isbn" if exact_isbn else "bibliographic",
        metadata=LiteratureMetadata(
            title=" : ".join(filter(None, [info.title, info.subtitle])) or None,
            authors=info.authors,
            year=year.group(1) if year else None,
            publisher=info.publisher,
            isbn=[
                identifier.identifier
                for identifier in info.industry_identifiers
                if identifier.type in {"ISBN_10", "ISBN_13"}
            ],
            work_type="book" if info.print_type == "BOOK" else None,
            url=info.info_link,
        ),
    )
