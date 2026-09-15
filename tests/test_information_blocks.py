import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from knowledge.information_blocks import (
    InformationBlock,
    InformationBlocks,
    SourceSpan,
    TextExtraction,
    extract_text,
    segment_information,
    segment_verbatim,
    text_revision,
    validate_blocks,
)


def extraction(pages=("First observation.\n\nSecond observation.", "A separate page.")):
    digest = hashlib.sha256(b"manually reviewed fixture").hexdigest()
    return TextExtraction(
        pdf_sha256=digest,
        revision=text_revision(digest, pages, "fixture-v1"),
        pages=pages,
        method="fixture-v1",
    )


def test_paragraph_segmentation_preserves_independently_known_offsets():
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
def test_sources_reject_wrong_revision_page_offsets_and_quote(changes, message):
    document = extraction()
    span = SourceSpan(
        extraction_revision=document.revision, page=1, start=0, end=18, quote="First observation."
    ).model_copy(update=changes)
    blocks = InformationBlocks(
        blocks=[InformationBlock(bullets=["Summary"], sources=[span], wording="paraphrase")]
    )
    with pytest.raises(ValueError, match=message):
        validate_blocks(blocks, document)


def test_extraction_revision_detects_changed_text_and_method():
    document = extraction()
    for change in [{"pages": ["Changed text"]}, {"method": "another-tool"}]:
        with pytest.raises(ValidationError, match="does not match"):
            TextExtraction.model_validate(document.model_dump() | change)


def test_verbatim_cannot_disguise_paraphrases():
    document = extraction()
    result = segment_verbatim(document)
    result.blocks[0].bullets = ["A different observation."]
    with pytest.raises(ValueError, match="Verbatim bullets"):
        validate_blocks(result, document)
    result.blocks[0].wording = "paraphrase"
    validate_blocks(result, document)


def test_pdf_operation_preserves_shared_extraction_qa(tmp_path, monkeypatch):
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"PDF fixture boundary")

    monkeypatch.setattr(
        "knowledge.ingestion.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=b"A short page.\f"),
    )
    with pytest.raises(ValueError, match="manual extraction QA"):
        extract_text(pdf)


def test_model_segmentation_uses_shared_adapter_and_domain_validation(tmp_path, monkeypatch):
    document = extraction()
    requests = []

    def respond(arguments, **kwargs):
        requests.append(json.loads(Path(arguments[-2]).read_text()))
        result = segment_verbatim(document).model_dump()
        if len(requests) == 1:
            result["blocks"][0]["sources"][0]["quote"] = "Fabricated quotation"
        Path(arguments[-1]).write_text(json.dumps({"response": json.dumps(result)}))

    monkeypatch.setattr("knowledge.generation.subprocess.run", respond)
    result = segment_information(document, "Group observations", tmp_path)
    assert len(result.blocks) == 3
    assert len(requests) == 2
    assert requests[0]["instructions"] == "Group observations"
    assert document.revision in requests[0]["input"]
    assert "exact page offsets" in requests[1]["input"]


def test_deterministic_segmentation_rejects_unbounded_result():
    with pytest.raises(ValueError, match="500 blocks"):
        segment_verbatim(extraction(("x" * 501,)), max_characters=1)
