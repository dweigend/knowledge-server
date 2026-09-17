import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from knowledge.source_workflows.information_block_extraction import (
    BlockProposal,
    BlockSegmentation,
    InformationBlock,
    InformationBlocks,
    QuoteReference,
    SourceSpan,
    TextExtraction,
    extract_text,
    resolve_segmentation,
    resolve_source_quote,
    segment_information,
    segment_verbatim,
    text_revision,
    validate_blocks,
    validate_segment_budget,
)


def extraction(
    pages: tuple[str, ...] = ("First observation.\n\nSecond observation.", "A separate page."),
) -> TextExtraction:
    digest = hashlib.sha256(b"manually reviewed fixture").hexdigest()
    return TextExtraction(
        pdf_sha256=digest,
        revision=text_revision(digest, pages, "fixture-v1"),
        pages=pages,
        method="fixture-v1",
    )


def test_paragraph_segmentation_preserves_independently_known_offsets() -> None:
    result = segment_verbatim(extraction())
    assert [block.bullets for block in result.blocks] == [
        ["First observation."],
        ["Second observation."],
        ["A separate page."],
    ]
    spans = [block.sources[0] for block in result.blocks]
    assert [(span.page, span.start, span.end) for span in spans] == [
        (1, 0, 18),
        (1, 20, 39),
        (2, 0, 16),
    ]
    assert all(block.wording == "verbatim" for block in result.blocks)


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"extraction_revision": "a" * 64}, "different extraction"),
        ({"page": 3}, "missing original"),
        ({"start": 1}, "exact page offsets"),
        ({"end": 100}, "outside"),
        ({"quote": "Invented observation"}, "exact page offsets"),
    ],
)
def test_sources_reject_wrong_revision_page_offsets_and_quote(
    changes: dict[str, object], message: str
) -> None:
    document = extraction()
    span = SourceSpan(
        extraction_revision=document.revision, page=1, start=0, end=18, quote="First observation."
    ).model_copy(update=changes)
    blocks = InformationBlocks(
        blocks=[InformationBlock(bullets=["Summary"], sources=[span], wording="paraphrase")]
    )
    with pytest.raises(ValueError, match=message):
        validate_blocks(blocks, document)


def test_extraction_revision_detects_changed_text_and_method() -> None:
    document = extraction()
    for change in [{"pages": ["Changed text"]}, {"method": "another-tool"}]:
        with pytest.raises(ValidationError, match="does not match"):
            TextExtraction.model_validate(document.model_dump() | change)


def test_verbatim_cannot_disguise_paraphrases() -> None:
    document = extraction()
    result = segment_verbatim(document)
    result.blocks[0].bullets = ["A different observation."]
    with pytest.raises(ValueError, match="Verbatim bullets"):
        validate_blocks(result, document)
    result.blocks[0].wording = "paraphrase"
    validate_blocks(result, document)


def test_pdf_operation_accepts_readable_single_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"PDF fixture boundary")

    monkeypatch.setattr(
        "knowledge.document_processing.pdf_text_extraction.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=b"A short page.\f"),
    )
    assert extract_text(pdf).pages == ("A short page.",)


def test_pdf_operation_rejects_empty_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"PDF fixture boundary")
    monkeypatch.setattr(
        "knowledge.document_processing.pdf_text_extraction.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=b"\f"),
    )
    with pytest.raises(ValueError, match="manual extraction QA"):
        extract_text(pdf)


def test_model_segmentation_uses_shared_adapter_and_domain_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = extraction()
    requests = []

    def respond(arguments: list[str], **kwargs: object) -> None:
        requests.append(json.loads(Path(arguments[-2]).read_text()))
        result = segment_verbatim(document).model_dump()
        for block in result["blocks"]:
            block["sources"] = [
                {"page": source["page"], "quote": source["quote"]} for source in block["sources"]
            ]
        if len(requests) == 1:
            result["blocks"][0]["sources"][0]["quote"] = "Fabricated quotation"
        Path(arguments[-1]).write_text(json.dumps({"response": json.dumps(result)}))

    monkeypatch.setattr("knowledge.model_integration.structured_generation.subprocess.run", respond)
    result = segment_information(document, "Group observations", tmp_path)
    assert len(result.blocks) == 3
    assert len(requests) == 2
    assert requests[0]["instructions"] == "Group observations"
    assert document.revision in requests[0]["input"]
    assert "exact wording match" in requests[1]["input"]
    schema = json.loads(requests[0]["input"].removeprefix("SCHEMA:\n").split("\n\nINPUT:")[0])
    assert set(schema["$defs"]["QuoteReference"]["properties"]) == {"page", "quote"}


def test_deterministic_segmentation_rejects_unbounded_result() -> None:
    with pytest.raises(ValueError, match="500 blocks"):
        segment_verbatim(extraction(("x" * 501,)), max_characters=1)


def test_model_segmentation_source_budget_is_an_enforced_constraint() -> None:
    document = extraction(("First observation.",))
    blocks = segment_verbatim(document)
    validate_segment_budget(blocks, document, 18)
    with pytest.raises(ValueError, match="max_source_characters"):
        validate_segment_budget(blocks, document, 17)


def test_quote_resolver_computes_offsets_without_changing_pdf_typography() -> None:
    document = extraction(("Heading\n\nA  ﬁnding\nspans lines.\nEnd.",))
    span = resolve_source_quote(QuoteReference(page=1, quote="A  ﬁnding\nspans lines."), document)
    assert (span.start, span.end) == (9, 31)
    assert span.quote == "A  ﬁnding\nspans lines."
    assert span.extraction_revision == document.revision
    assert document.pages[0][span.start : span.end] == span.quote


@pytest.mark.parametrize(
    "pages,page,quote",
    [
        (("Same finding. Same finding.",), 1, "Same finding."),
        (("A finding.", "A different page."), 2, "A finding."),
        (("A finding.",), 2, "A finding."),
        (("A finding.",), 1, "Another finding."),
        (("A finding.",), 1, "a finding."),
        (("A  ﬁnding\nspans lines.",), 1, "A finding spans lines."),
    ],
)
def test_quote_resolver_rejects_ambiguity_wrong_page_and_changed_wording(
    pages: tuple[str, ...], page: int, quote: str
) -> None:
    with pytest.raises(ValueError):
        resolve_source_quote(QuoteReference(page=page, quote=quote), extraction(pages))


def test_segmentation_resolver_retains_paraphrases_without_calling_them_quotes() -> None:
    document = extraction(("A finding.",))
    proposal = BlockSegmentation(
        blocks=[
            BlockProposal(
                bullets=["A concise interpretation."],
                sources=[QuoteReference(page=1, quote="A finding.")],
                wording="paraphrase",
            )
        ]
    )
    blocks = resolve_segmentation(proposal, document)
    assert blocks.blocks[0].bullets == ["A concise interpretation."]
    assert blocks.blocks[0].sources[0].quote == "A finding."
    proposal.blocks[0].wording = "verbatim"
    with pytest.raises(ValueError, match="Verbatim bullets"):
        resolve_segmentation(proposal, document)
