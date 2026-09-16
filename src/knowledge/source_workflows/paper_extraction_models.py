"""Validate document analysis settings independently of recipe execution."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from knowledge.literature.reference_discovery_models import DiscoverySettings


class PaperExtractionSettings(BaseModel):
    """Select compatible document and literature providers from a shared recipe."""

    model_config = ConfigDict(extra="ignore", strict=True)

    document_provider: Literal["poppler", "grobid"] = "poppler"
    literature_provider: Literal["none", "crossref", "discovery"] = "none"
    service_url: str = ""
    discovery: DiscoverySettings = Field(default_factory=DiscoverySettings)

    @model_validator(mode="after")
    def compatible_providers(self) -> "PaperExtractionSettings":
        """Require structured extraction before requesting literature metadata."""
        if self.document_provider == "grobid":
            validate_service_url(self.service_url)
            return self
        if self.literature_provider != "none":
            raise ValueError("Literature matching requires structured document extraction")
        if "service_url" in self.model_fields_set:
            raise ValueError("service_url is only supported for grobid")
        return self


def validate_service_url(location: str) -> None:
    """Require an HTTP analyzer address without credentials or request parameters."""
    parsed = urlsplit(location)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("GROBID requires an HTTP service_url")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("service_url must not contain credentials, query or fragment")
