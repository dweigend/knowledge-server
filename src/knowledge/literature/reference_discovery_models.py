"""Describe reference searches and their inspectable evidence."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

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
    """Configure optional providers and metadata requirements."""

    model_config = ConfigDict(extra="ignore", strict=True)

    providers: Annotated[list[Provider], AfterValidator(unique_providers)] = Field(
        default=["dnb", "openalex", "openlibrary"]
    )
    required_fields: Annotated[list[RequiredField], AfterValidator(unique_requirements)] = Field(
        default=["title", "authors", "year"]
    )
    find_open_access: bool = False


class SearchQuery(BaseModel):
    """Record one provider query without credentials or response bodies."""

    model_config = ConfigDict(extra="ignore")

    provider: str
    query: str
    status: Literal["success", "error", "skipped"]
    message: str = ""
    candidate_count: int = 0


class ReferenceSearch(BaseModel):
    """Explain why one source required lookup and which queries ran."""

    reference_id: str
    trigger: str
    queries: list[SearchQuery] = Field(default_factory=list)


class RefinementAudit(BaseModel):
    """Report whether model-assisted query refinement ran."""

    status: Literal["not_needed", "completed", "skipped", "failed"] = "not_needed"
    reason: str = ""
    planned_queries: int = 0


class DiscoveryReport(BaseModel):
    """Expose unresolved quality issues and searches without claiming completeness."""

    warnings: list[str] = Field(default_factory=list)
    searches: list[ReferenceSearch] = Field(default_factory=list)
    refinement: RefinementAudit = Field(default_factory=RefinementAudit)
