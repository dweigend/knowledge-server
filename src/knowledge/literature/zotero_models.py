"""Validate the Zotero response fields used by literature and attachment workflows."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Creator(BaseModel):
    """Describe a personal or institutional Zotero creator."""

    creatorType: str = ""
    name: str = ""
    firstName: str = ""
    lastName: str = ""


class Tag(BaseModel):
    """Identify an attachment recovery or import tag."""

    model_config = ConfigDict(extra="allow")

    tag: str


class ItemData(BaseModel):
    """Read bibliographic and attachment fields from a Zotero item."""

    key: str = ""
    title: str = ""
    creators: list[Creator] = Field(default_factory=list)
    date: str = ""
    DOI: str = ""
    url: str = ""
    publicationTitle: str = ""
    bookTitle: str = ""
    versionNumber: str = ""
    type: str = ""
    version: int = 0
    contentType: str = ""
    linkMode: str = ""
    tags: list[Tag] = Field(default_factory=list)


class Item(BaseModel):
    """Read a Zotero item envelope with optional formatted citations."""

    key: str = ""
    data: ItemData
    bib: str = ""
    bibtex: str = ""


class ItemKey(BaseModel):
    """Identify a created or reconciled Zotero item."""

    key: str


class WriteResult(BaseModel):
    """Read successful Zotero item creation results."""

    successful: dict[str, ItemKey]


class UploadAuthorization(BaseModel):
    """Describe a local upload destination when bytes are not already stored."""

    exists: bool = False
    url: str = ""
    contentType: str = ""
    uploadKey: str = ""

    @model_validator(mode="after")
    def require_upload_destination(self) -> Self:
        """Reject incomplete upload instructions before sending any PDF bytes."""
        if self.exists:
            return self
        if not self.url or not self.contentType or not self.uploadKey:
            raise ValueError("Zotero upload requires url, contentType and uploadKey")
        return self
