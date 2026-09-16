"""Describe bounded reference searches and their inspectable evidence."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from knowledge.literature.literature_models import Candidate

Provider = Literal["dnb", "openalex", "openlibrary", "semantic_scholar", "google_books"]
RequiredField = Literal["title", "authors", "year", "venue", "publisher", "pages", "doi"]


class DiscoverySettings(BaseModel):
    """Limit optional searches while retaining unsuccessful results until explicit retry."""

    model_config = ConfigDict(extra="forbid", strict=True)

    providers: list[Provider] = Field(default=["dnb", "openalex", "openlibrary"])
    required_fields: list[RequiredField] = Field(default=["title", "authors", "year"])
    max_requests: int = Field(default=40, ge=0, le=200)
    max_requests_per_reference: int = Field(default=5, ge=1, le=12)
    max_model_calls: int = Field(default=2, ge=0, le=5)
    model_timeout_seconds: float = Field(default=60, ge=1, le=120)
    retry_generation: int = Field(default=0, ge=0)
    find_open_access: bool = False

    @model_validator(mode="after")
    def unique_options(self) -> "DiscoverySettings":
        """Reject duplicate providers or requirements that obscure search budgets."""
        if len(set(self.providers)) != len(self.providers):
            raise ValueError("Discovery providers must be unique")
        if not self.required_fields or len(set(self.required_fields)) != len(self.required_fields):
            raise ValueError("Required fields must be nonempty and unique")
        return self


class SearchQuery(BaseModel):
    """Record one provider query without credentials or unbounded response bodies."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    query: str
    status: Literal["success", "error", "budget", "backoff", "skipped"]
    cached: bool = False
    message: str = ""
    candidate_count: int = 0


class ReferenceSearch(BaseModel):
    """Explain why one source required lookup and which bounded queries ran."""

    reference_id: str
    trigger: str
    queries: list[SearchQuery] = Field(default_factory=list)


class DiscoveryReport(BaseModel):
    """Expose resource usage and unresolved quality issues without claiming completeness."""

    requests: int = 0
    cache_hits: int = 0
    model_calls: int = 0
    warnings: list[str] = Field(default_factory=list)
    searches: list[ReferenceSearch] = Field(default_factory=list)


class CachedLookup(BaseModel):
    """Retain a provider's positive or negative result for an identical request."""

    model_config = ConfigDict(extra="forbid")

    candidates: list[Candidate] = Field(default_factory=list)
    error: str | None = None
    checked_at: str
