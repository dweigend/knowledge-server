import hashlib
from pathlib import Path
from typing import Never

import pytest
from test_experimentation import fixture_pdf

from knowledge.literature.structured_paper_models import PaperDocument, PaperMetadata
from knowledge.source_workflows.information_block_extraction import TextExtraction, segment_verbatim
from knowledge.source_workflows.structured_paper_extraction import (
    extract_paper_document,
    validate_paper_parameters,
)
from knowledge.web_interface.paper_markdown_renderer import render_paper_markdown


def paper() -> PaperDocument:
    return PaperDocument(
        markdown="# A paper\n\n## Findings\n\nFirst observation.",
        metadata=PaperMetadata(title="A paper", authors=["A. Researcher"], year="2026"),
        provider="test-analyzer",
        raw_document="<provider-output />",
    )


def test_replaceable_analyzer_preserves_exact_page_quotes_and_private_artifacts(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(fixture_pdf())
    received = []

    def analyzer(source: Path, **settings: object) -> PaperDocument:
        received.append((source, settings))
        return paper()

    result = extract_paper_document(
        pdf,
        {"document_provider": "grobid", "service_url": "http://localhost:8070"},
        tmp_path / "trace",
        timeout_seconds=10,
        cancelled=lambda: False,
        analyzer=analyzer,
    )
    assert received[0][0] == pdf
    timeout = received[0][1]["timeout_seconds"]
    assert isinstance(timeout, (int, float))
    assert 0 < timeout <= 10
    assert result.pdf_sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert result.paper is not None
    assert result.paper.metadata.title == "A paper"
    assert result.paper.raw_document is None
    assert (tmp_path / "trace/provider-response.txt").read_text() == "<provider-output />"
    assert (tmp_path / "trace/document.md").read_text().startswith("# A paper")
    assert TextExtraction.model_validate_json(result.model_dump_json()) == result
    span = segment_verbatim(result).blocks[0].sources[0]
    assert result.pages[span.page - 1][span.start : span.end] == span.quote


def test_explicit_raw_text_mode_does_not_contact_analyzer(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(fixture_pdf())

    def unexpected(*args: object, **kwargs: object) -> Never:
        raise AssertionError("Raw extraction contacted the service")

    result = extract_paper_document(
        pdf,
        {"document_provider": "poppler"},
        tmp_path / "trace",
        timeout_seconds=10,
        cancelled=lambda: False,
        analyzer=unexpected,
    )
    assert result.paper is None
    assert "First observation." in result.pages[0]


def test_analyzer_failure_does_not_silently_return_raw_success(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(fixture_pdf())

    def unavailable(*args: object, **kwargs: object) -> Never:
        raise ValueError("service unavailable")

    with pytest.raises(ValueError, match="service unavailable"):
        extract_paper_document(
            pdf,
            {"document_provider": "grobid", "service_url": "http://localhost:8070"},
            tmp_path / "trace",
            timeout_seconds=10,
            cancelled=lambda: False,
            analyzer=unavailable,
        )


@pytest.mark.parametrize(
    "parameters",
    [
        {"document_provider": "invented"},
        {"document_provider": "grobid"},
        {"document_provider": "grobid", "service_url": "file:///tmp/service"},
        {"document_provider": "grobid", "service_url": "http://user:password@localhost"},
        {"document_provider": "poppler", "service_url": "http://localhost"},
    ],
)
def test_invalid_provider_configuration_is_rejected(parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        validate_paper_parameters(parameters)


def test_document_markdown_renders_headings_without_executable_html_or_remote_images() -> None:
    rendered = str(
        render_paper_markdown(
            "# Heading\n\n<script>alert(1)</script>\n\n![image](https://remote/image.png)\n"
            "[bad](javascript:alert(1))"
        )
    )
    assert "<h1>Heading</h1>" in rendered
    assert "<script>" not in rendered
    assert "<img" not in rendered
    assert 'href="javascript:' not in rendered


@pytest.mark.parametrize("suffix", ["?token=secret", "#fragment"])
def test_service_url_rejects_query_and_fragment(suffix: str) -> None:
    with pytest.raises(ValueError, match="credentials, query or fragment"):
        validate_paper_parameters(
            {
                "document_provider": "grobid",
                "service_url": f"http://localhost:8070{suffix}",
            }
        )


def test_extraction_settings_accept_unrelated_recipe_fields_without_coercing_limits() -> None:
    from knowledge.source_workflows.paper_extraction_models import PaperExtractionSettings

    settings = PaperExtractionSettings.model_validate({"max_characters": 200, "prompt": "custom"})
    assert settings.document_provider == "poppler"
    with pytest.raises(ValueError):
        PaperExtractionSettings.model_validate({"discovery": {"max_requests": "10"}})


@pytest.mark.parametrize("interrupt", ["source_changed", "cancelled"])
def test_analysis_rejects_invalidated_evidence_before_writing_artifacts(
    tmp_path: Path, interrupt: str
) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(fixture_pdf())
    stopped = False

    def analyzer(source: Path, **settings: object) -> PaperDocument:
        nonlocal stopped
        if interrupt == "source_changed":
            source.write_bytes(b"changed")
        else:
            stopped = True
        return paper()

    error = ValueError if interrupt == "source_changed" else InterruptedError
    with pytest.raises(error):
        extract_paper_document(
            pdf,
            {"document_provider": "grobid", "service_url": "http://localhost:8070"},
            tmp_path / "trace",
            timeout_seconds=10,
            cancelled=lambda: stopped,
            analyzer=analyzer,
        )
    assert not (tmp_path / "trace").exists()
