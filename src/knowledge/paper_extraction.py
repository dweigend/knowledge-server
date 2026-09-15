"""Combine replaceable paper analysis with independently pinned original PDF text."""

import hashlib
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from typing import Protocol
from urllib.parse import urlsplit

from knowledge.grobid_client import extract_paper
from knowledge.information_blocks import TextExtraction, extract_text
from knowledge.paper_contracts import PaperDocument


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
    ) -> PaperDocument:
        """Return normalized document structure and bibliographic evidence."""
        ...


def validate_paper_parameters(parameters: dict) -> None:
    """Reject unsupported analyzers and malformed service locations before execution."""
    provider = parameters.get("document_provider", "poppler")
    if not isinstance(provider, str) or provider not in {"poppler", "grobid"}:
        raise ValueError("document_provider must be grobid or poppler")
    if provider == "poppler":
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
    analyzer: PaperAnalyzer = extract_paper,
) -> TextExtraction:
    """Preserve exact page evidence and attach provider-neutral document analysis."""
    validate_paper_parameters(parameters)
    started = monotonic()
    extraction = extract_text(pdf, cancelled=cancelled, timeout_seconds=timeout_seconds)
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
    output_directory.mkdir(parents=True, exist_ok=True)
    if paper.raw_document is not None:
        (output_directory / "provider-response.txt").write_text(
            paper.raw_document, encoding="utf-8"
        )
    (output_directory / "document.md").write_text(paper.markdown, encoding="utf-8")
    return extraction.model_copy(update={"paper": paper.model_copy(update={"raw_document": None})})
