"""Run fresh provider queries for one discovery execution."""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from knowledge.literature import literature_resolution
from knowledge.literature import reference_discovery_models as models
from knowledge.literature.bibliographic_identifiers import extracted_isbn
from knowledge.literature.literature_models import Candidate
from knowledge.literature.structured_paper_models import PaperMetadata, PaperReference


def query_text(reference: PaperMetadata) -> str:
    """Expose only bibliographic search evidence in the result."""
    if isinstance(reference, PaperReference) and reference.raw:
        return reference.raw
    return " · ".join(
        filter(None, [reference.title, *reference.authors, reference.year, reference.doi])
    )


def supports_query(provider: str, reference: PaperMetadata) -> bool:
    """Skip adapters that cannot search the supplied fields."""
    if provider == "crossref":
        return bool(reference.title or reference.doi or getattr(reference, "raw", None))
    if provider == "unpaywall":
        return bool(reference.doi)
    if provider in {"openalex", "semantic_scholar"} and reference.doi:
        return True
    if provider in {"dnb", "openlibrary", "google_books"} and extracted_isbn(reference):
        return True
    return bool(reference.title)


class ReferenceSearchSession(BaseModel):
    """Own provider access and the current discovery report."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    settings: models.DiscoverySettings
    report: models.DiscoveryReport
    cancelled: Callable[[], bool]
    providers: dict[str, literature_resolution.Lookup]

    def search(
        self, provider: str, reference: PaperReference, trace: models.ReferenceSearch
    ) -> list[Candidate]:
        """Run one provider query for the current execution."""
        self.check_cancelled()
        query = models.SearchQuery(provider=provider, query=query_text(reference), status="success")
        trace.queries.append(query)
        if provider not in self.providers:
            query.status = "error"
            query.message = "Provider is not configured; no request made."
            candidates: list[Candidate] = []
        elif not supports_query(provider, reference):
            query.status = "skipped"
            query.message = "Insufficient fields for this provider; no request made."
            candidates = []
        else:
            candidates = self.request(provider, reference, query)
            query.candidate_count = len(candidates)
        return candidates

    def request(
        self,
        provider: str,
        reference: PaperReference,
        query: models.SearchQuery,
    ) -> list[Candidate]:
        """Call one provider and record recoverable transport failures on the query."""
        self.check_cancelled()
        try:
            return self.providers[provider](
                reference,
                literature_resolution.MAX_LOOKUP_SECONDS,
                self.cancelled,
            )
        except InterruptedError:
            raise
        except (OSError, ValueError) as error:
            self.record_failure(provider, error, query)
            return []

    def record_failure(
        self, provider: str, error: OSError | ValueError, query: models.SearchQuery
    ) -> None:
        """Redact provider failure details in the current query result."""
        query.status = "error"
        if "429" not in str(error):
            query.message = f"{provider}: {type(error).__name__}"
            return
        query.message = f"{provider}: HTTP 429"

    def check_cancelled(self) -> None:
        """Stop immediately when the owning experiment is cancelled."""
        if self.cancelled():
            raise InterruptedError("Reference discovery cancelled")
