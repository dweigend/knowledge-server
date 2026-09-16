"""Run bounded provider queries with persistent positive and negative caching."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep

from knowledge.literature import literature_resolution
from knowledge.literature import reference_discovery_models as models
from knowledge.literature.bibliographic_identifiers import extracted_isbn
from knowledge.literature.literature_models import Candidate
from knowledge.literature.structured_paper_models import PaperMetadata, PaperReference
from knowledge.runtime_support.atomic_json_files import write_json_atomically

CACHE_VERSION = "reference-search.v3"
MIN_REQUEST_INTERVAL_SECONDS = 1
CANCELLATION_POLL_SECONDS = 0.05
MIN_LOOKUP_SECONDS = 0.001


def request_key(provider: str, reference: PaperMetadata, retry_generation: int) -> str:
    """Hash the effective query and explicit retry revision, excluding local reference IDs."""
    payload = [CACHE_VERSION, provider, reference.model_dump(exclude={"id"}), retry_generation]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def query_text(reference: PaperMetadata) -> str:
    """Expose only bibliographic search evidence in the attempt trace."""
    if isinstance(reference, PaperReference) and reference.raw:
        return reference.raw
    return " · ".join(
        filter(None, [reference.title, *reference.authors, reference.year, reference.doi])
    )


def supports_query(provider: str, reference: PaperMetadata) -> bool:
    """Avoid spending request budgets on adapters that cannot search the supplied fields."""
    if provider == "crossref":
        return bool(reference.title or reference.doi or getattr(reference, "raw", None))
    if provider == "unpaywall":
        return bool(reference.doi)
    if provider in {"openalex", "semantic_scholar"} and reference.doi:
        return True
    if provider in {"dnb", "openlibrary", "google_books"} and extracted_isbn(reference):
        return True
    return bool(reference.title)


@dataclass
class ReferenceSearchSession:
    """Own request budgets, per-provider backoff and private cache files for one run."""

    cache_directory: Path
    settings: models.DiscoverySettings
    report: models.DiscoveryReport
    deadline: float
    cancelled: Callable[[], bool]
    providers: dict[str, literature_resolution.Lookup]
    state: models.LookupState = field(default_factory=models.LookupState)

    def search(
        self, provider: str, reference: PaperReference, trace: models.ReferenceSearch
    ) -> list[Candidate]:
        """Reuse identical results before spending either request or per-reference budget."""
        self.check_cancelled()
        query = models.SearchQuery(provider=provider, query=query_text(reference), status="success")
        trace.queries.append(query)
        if provider not in self.providers:
            query.status = "error"
            query.message = "Provider is not configured; no request made."
            return []
        if not supports_query(provider, reference):
            query.status = "skipped"
            query.message = "Insufficient fields for this provider; no request made."
            return []
        result = self.lookup(provider, reference, trace.reference_id, query)
        if result is None:
            return []
        query.candidate_count = len(result.candidates)
        query.message = result.error or ""
        query.status = "error" if result.error else "success"
        return result.candidates

    def lookup(
        self,
        provider: str,
        reference: PaperReference,
        reference_id: str,
        query: models.SearchQuery,
    ) -> models.CachedLookup | None:
        """Read cached evidence or persist a fresh lookup only when budgets permit it."""
        key = request_key(provider, reference, self.settings.retry_generation)
        path = self.cache_directory / f"{key}.json"
        if path.exists():
            result = models.CachedLookup.model_validate_json(path.read_text())
            query.cached = True
            self.report.cache_hits += 1
            return result

        reason = self.wait_for_capacity(provider, reference_id)
        if reason:
            query.status = "backoff" if provider in self.state.backoff else "budget"
            query.message = reason
            return None

        result = self.request(provider, reference, reference_id)
        write_json_atomically(path, result.model_dump(mode="json"))
        return result

    def wait_for_capacity(self, provider: str, reference_id: str) -> str | None:
        """Check budgets before and after cancellable provider pacing."""
        reason = self.stop_reason(provider, reference_id)
        if reason:
            return reason
        self.wait_for_provider(provider)
        self.check_cancelled()
        return self.stop_reason(provider, reference_id)

    def stop_reason(self, provider: str, reference_id: str) -> str | None:
        """Explain why a fresh request cannot run without caching a synthetic failure."""
        if provider in self.state.backoff:
            return "Provider rate limited this run; another provider may still be used."
        if monotonic() >= self.deadline:
            return "Search time budget exhausted."
        if self.report.requests >= self.settings.max_requests:
            return "Search request budget exhausted."
        if (
            self.state.reference_requests.get(reference_id, 0)
            >= self.settings.max_requests_per_reference
        ):
            return "Per-reference request budget exhausted."
        return None

    def request(
        self, provider: str, reference: PaperReference, reference_id: str
    ) -> models.CachedLookup:
        """Call one provider and preserve recoverable transport failures as explicit results."""
        self.check_cancelled()
        remaining = self.deadline - monotonic()
        self.report.requests += 1
        self.state.reference_requests[reference_id] = (
            self.state.reference_requests.get(reference_id, 0) + 1
        )
        self.state.last_requests[provider] = monotonic()
        checked_at = datetime.now(UTC).isoformat()
        try:
            candidates = self.providers[provider](
                reference,
                max(MIN_LOOKUP_SECONDS, min(literature_resolution.MAX_LOOKUP_SECONDS, remaining)),
                self.cancelled,
            )
        except InterruptedError:
            raise
        except (OSError, ValueError) as error:
            return self.failed_lookup(provider, error, checked_at)
        return models.CachedLookup(candidates=candidates, checked_at=checked_at)

    def failed_lookup(
        self, provider: str, error: OSError | ValueError, checked_at: str
    ) -> models.CachedLookup:
        """Redact provider failure details and pause only a rate-limited provider."""
        if "429" not in str(error):
            return models.CachedLookup(
                error=f"{provider}: {type(error).__name__}", checked_at=checked_at
            )
        self.state.backoff.add(provider)
        return models.CachedLookup(error=f"{provider}: HTTP 429", checked_at=checked_at)

    def wait_for_provider(self, provider: str) -> None:
        """Pace sequential requests while remaining responsive to cancellation."""
        ready = min(
            self.state.last_requests.get(provider, 0) + MIN_REQUEST_INTERVAL_SECONDS, self.deadline
        )
        while monotonic() < ready:
            self.check_cancelled()
            sleep(min(CANCELLATION_POLL_SECONDS, max(0, ready - monotonic())))

    def check_cancelled(self) -> None:
        """Stop immediately when the owning experiment is cancelled."""
        if self.cancelled():
            raise InterruptedError("Reference discovery cancelled")
