"""Extract a structured paper while independently pinning original PDF text.

The workflow validates analyzer parameters, resolves literature references, and
stores inspectable artifacts for downstream steps.
"""

import hashlib
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from typing import Protocol
from urllib.parse import urlsplit

from knowledge.literature import grobid_client, literature_resolution, structured_paper_models
from knowledge.literature.reference_discovery_models import DiscoverySettings
from knowledge.model_integration.structured_generation import ModelConfiguration
from knowledge.source_workflows import information_block_extraction, reference_discovery


class PaperAnalyzer(Protocol):
    """Analyze a PDF without coupling the workflow to a provider response format."""

    def __call__(
        self,
        pdf: Path,
        /,
        *,
        base_url: str,
        timeout_seconds: float,
        cancelled: Callable[[], bool] | None = None,
    ) -> structured_paper_models.PaperDocument:
        """Return normalized document structure and bibliographic evidence."""
        ...


def validate_paper_parameters(parameters: dict) -> None:
    """Reject unsupported analyzers and malformed service locations before execution."""
    literature = parameters.get("literature_provider", "none")
    if not isinstance(literature, str) or literature not in {"none", "crossref", "discovery"}:
        raise ValueError("literature_provider must be discovery, crossref or none")
    DiscoverySettings.model_validate(parameters.get("discovery", {}))
    provider = parameters.get("document_provider", "poppler")
    if not isinstance(provider, str) or provider not in {"poppler", "grobid"}:
        raise ValueError("document_provider must be grobid or poppler")
    if provider == "poppler":
        if literature != "none":
            raise ValueError("Literature matching requires structured document extraction")
        if "service_url" in parameters:
            raise ValueError("service_url is only supported for grobid")
        return
    location = parameters.get("service_url", "")
    if not isinstance(location, str):
        raise ValueError("service_url must be an HTTP service URL")
    parsed = urlsplit(location)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("GROBID requires an HTTP service_url")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("service_url must not contain credentials, query or fragment")


def extract_paper_document(
    pdf: Path,
    parameters: dict,
    output_directory: Path,
    *,
    timeout_seconds: float,
    cancelled: Callable[[], bool],
    analyzer: PaperAnalyzer = grobid_client.extract_paper,
    configuration: ModelConfiguration | None = None,
    cache_directory: Path | None = None,
) -> information_block_extraction.TextExtraction:
    """Preserve exact page evidence and attach provider-neutral document analysis."""
    validate_paper_parameters(parameters)
    started = monotonic()
    extraction = information_block_extraction.extract_text(
        pdf, cancelled=cancelled, timeout_seconds=timeout_seconds
    )
    if parameters.get("document_provider", "poppler") == "poppler":
        return extraction
    if cancelled():
        raise InterruptedError("Paper extraction cancelled")
    remaining = timeout_seconds - (monotonic() - started)
    if remaining <= 0:
        raise TimeoutError("Paper extraction exceeded its time limit")
    paper = analyzer(
        pdf, base_url=parameters["service_url"], timeout_seconds=remaining, cancelled=cancelled
    )
    if cancelled():
        raise InterruptedError("Paper extraction cancelled")
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != extraction.pdf_sha256:
        raise ValueError("PDF changed during paper analysis")
    save_paper_artifacts(paper, output_directory)
    if parameters.get("literature_provider") == "discovery":
        remaining = timeout_seconds - (monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("Paper extraction exceeded its time limit")
        result = reference_discovery.discover_references(
            paper,
            list(extraction.pages),
            extraction.pdf_sha256,
            output_directory,
            cache_directory or output_directory / "reference-cache",
            settings=DiscoverySettings.model_validate(parameters.get("discovery", {})),
            configuration=configuration or ModelConfiguration(),
            timeout_seconds=max(0.1, remaining - 1),
            cancelled=cancelled,
        )
        return extraction.model_copy(
            update={
                "paper": result.paper.model_copy(update={"raw_document": None}),
                "literature": result.literature,
                "discovery": result.report,
                "bibliography": result.bibliography,
            }
        )
    records = []
    if parameters.get("literature_provider") == "crossref":
        records = literature_resolution.enrich_paper(
            paper,
            extraction.pdf_sha256,
            timeout_seconds=max(0.1, timeout_seconds - (monotonic() - started) - 1),
            cancelled=cancelled,
        )
    return extraction.model_copy(
        update={
            "paper": paper.model_copy(update={"raw_document": None}),
            "literature": records,
        }
    )


def save_paper_artifacts(
    paper: structured_paper_models.PaperDocument, output_directory: Path
) -> None:
    """Retain provider output and Markdown inside the owned attempt trace."""
    output_directory.mkdir(parents=True, exist_ok=True)
    if paper.raw_document is not None:
        (output_directory / "provider-response.txt").write_text(
            paper.raw_document, encoding="utf-8"
        )
    (output_directory / "document.md").write_text(paper.markdown, encoding="utf-8")
