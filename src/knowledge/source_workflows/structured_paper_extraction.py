"""Extract a structured paper while independently pinning original PDF text.

The workflow validates analyzer parameters, resolves literature references, and
stores inspectable artifacts for downstream steps.
"""

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from knowledge.literature import grobid_client, literature_resolution, structured_paper_models
from knowledge.model_integration.structured_generation import ModelConfiguration
from knowledge.source_workflows import information_block_extraction, reference_discovery
from knowledge.source_workflows.paper_extraction_models import PaperExtractionSettings


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


def validate_paper_parameters(parameters: Mapping[str, object]) -> None:
    """Reject unsupported analyzers and malformed service locations before execution."""
    PaperExtractionSettings.model_validate(parameters)


def extract_paper_document(
    pdf: Path,
    parameters: Mapping[str, object],
    *,
    timeout_seconds: float,
    cancelled: Callable[[], bool],
    analyzer: PaperAnalyzer = grobid_client.extract_paper,
    configuration: ModelConfiguration | None = None,
) -> information_block_extraction.TextExtraction:
    """Preserve exact page evidence and attach provider-neutral document analysis."""
    settings = PaperExtractionSettings.model_validate(parameters)
    extraction = information_block_extraction.extract_text(
        pdf, cancelled=cancelled, timeout_seconds=timeout_seconds
    )
    if settings.document_provider == "poppler":
        return extraction

    paper = analyze_document(pdf, extraction, settings, timeout_seconds, cancelled, analyzer)
    if settings.literature_provider == "discovery":
        return discover_literature(
            extraction,
            paper,
            settings,
            configuration or ModelConfiguration(),
            cancelled,
        )
    return attach_literature(extraction, paper, settings, timeout_seconds, cancelled)


def analyze_document(
    pdf: Path,
    extraction: information_block_extraction.TextExtraction,
    settings: PaperExtractionSettings,
    timeout_seconds: float,
    cancelled: Callable[[], bool],
    analyzer: PaperAnalyzer,
) -> structured_paper_models.PaperDocument:
    """Analyze the pinned PDF and reject cancellation or a changed source."""
    if cancelled():
        raise InterruptedError("Paper extraction cancelled")
    paper = analyzer(
        pdf,
        base_url=settings.service_url,
        timeout_seconds=timeout_seconds,
        cancelled=cancelled,
    )
    if cancelled():
        raise InterruptedError("Paper extraction cancelled")
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != extraction.pdf_sha256:
        raise ValueError("PDF changed during paper analysis")
    return paper


def discover_literature(
    extraction: information_block_extraction.TextExtraction,
    paper: structured_paper_models.PaperDocument,
    settings: PaperExtractionSettings,
    configuration: ModelConfiguration,
    cancelled: Callable[[], bool],
) -> information_block_extraction.TextExtraction:
    """Attach recovered bibliography and fresh discovery results to exact page evidence."""
    result = reference_discovery.discover_references(
        paper,
        list(extraction.pages),
        extraction.pdf_sha256,
        settings=settings.discovery,
        configuration=configuration,
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


def attach_literature(
    extraction: information_block_extraction.TextExtraction,
    paper: structured_paper_models.PaperDocument,
    settings: PaperExtractionSettings,
    timeout_seconds: float,
    cancelled: Callable[[], bool],
) -> information_block_extraction.TextExtraction:
    """Attach structured evidence and optional Crossref records without discovery."""
    result = extraction.model_copy(
        update={"paper": paper.model_copy(update={"raw_document": None})}
    )
    if settings.literature_provider != "crossref":
        return result
    literature = literature_resolution.enrich_paper(
        paper,
        extraction.pdf_sha256,
        timeout_seconds=timeout_seconds,
        cancelled=cancelled,
    )
    return result.model_copy(update={"literature": literature})
