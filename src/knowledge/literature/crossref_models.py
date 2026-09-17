"""Validate Crossref metadata while retaining its deposited field values."""

from pydantic import BaseModel, Field


class Author(BaseModel):
    """Describe a personal or organizational author."""

    given: str | None = None
    family: str | None = None
    name: str = ""


class PublicationDate(BaseModel):
    """Retain date components without coercing invalid years into integers."""

    date_parts: list[list[int | str | float | bool | None]] = Field(
        default_factory=list, alias="date-parts"
    )


class Metadata(BaseModel):
    """Describe the deposited fields used by literature resolution."""

    doi: str | None = Field(default=None, alias="DOI")
    title: list[str] = Field(default_factory=list)
    author: list[Author] = Field(default_factory=list)
    container_title: list[str] = Field(default_factory=list, alias="container-title")
    published: PublicationDate = Field(default_factory=PublicationDate)
    published_print: PublicationDate = Field(
        default_factory=PublicationDate, alias="published-print"
    )
    published_online: PublicationDate = Field(
        default_factory=PublicationDate, alias="published-online"
    )
    issued: PublicationDate = Field(default_factory=PublicationDate)
    publisher: str | None = None
    volume: str | None = None
    issue: str | None = None
    page: str | None = None
    type: str | None = None
    url: str | None = Field(default=None, alias="URL")
    isbn: list[str] = Field(default_factory=list, alias="ISBN")
    issn: list[str] = Field(default_factory=list, alias="ISSN")


class Work(Metadata):
    """Require the provider identifier for a retrieved work."""

    doi: str = Field(alias="DOI")


class Search(BaseModel):
    """Describe a bibliographic search result."""

    items: list[Work]


class Response(BaseModel):
    """Validate the Crossref work or search response envelope."""

    message: Work | Search
