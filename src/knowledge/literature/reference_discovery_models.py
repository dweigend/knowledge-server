"""Describe bounded reference searches and their inspectable evidence."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from knowledge.literature.literature_models import Candidate

Provider = Literal["dnb", "openalex", "openlibrary", "semantic_scholar", "google_books"]
RequiredField = Literal["title", "authors", "year", "venue", "publisher", "pages", "doi"]


def unique_providers(providers: list[Provider]) -> list[Provider]:
    """Reject duplicate providers without changing their search order."""
    if len(set(providers)) == len(providers):
        return providers
    raise ValueError("Discovery providers must be unique")


def unique_requirements(fields: list[RequiredField]) -> list[RequiredField]:
    """Require distinct metadata fields before a search can be considered complete."""
    if fields and len(set(fields)) == len(fields):
        return fields
    raise ValueError("Required fields must be nonempty and unique")


class DiscoverySettings(BaseModel):
    """Limit optional searches while retaining unsuccessful results until explicit retry."""

    model_config = ConfigDict(extra="forbid", strict=True)

    providers: Annotated[list[Provider], AfterValidator(unique_providers)] = Field(
        default=["dnb", "openalex", "openlibrary"]
    )
    required_fields: Annotated[list[RequiredField], AfterValidator(unique_requirements)] = Field(
        default=["title", "authors", "year"]
    )
    max_requests: int = Field(default=40, ge=0, le=200)
    max_requests_per_reference: int = Field(default=5, ge=1, le=12)
    max_model_calls: int = Field(default=2, ge=0, le=5)
    model_timeout_seconds: float = Field(default=60, ge=1, le=120)
    retry_generation: int = Field(default=0, ge=0)
    find_open_access: bool = False


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
