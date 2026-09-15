import json

import pytest

from knowledge.experimentation import create_experiment, read_manifest, run_step


def test_experiment_creation_isolated_and_step_execution_is_manual(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    experiment_id = create_experiment(archive, "paper.pdf", b"pdf bytes")
    manifest = read_manifest(archive, experiment_id)
    assert manifest["filename"] == "paper.pdf"
    assert manifest["steps"] == {}

    def fake_extract(path):
        from knowledge.information_blocks import TextExtraction, text_revision

        pages = ("A paragraph.",)
        digest = "0" * 64
        return TextExtraction(
            pdf_sha256=digest,
            revision=text_revision(digest, pages, "test"),
            pages=pages,
            method="test",
        )

    monkeypatch.setattr("knowledge.experimentation.extract_text", fake_extract)
    output = run_step(archive, experiment_id, "extract_text")
    assert output["pages"] == ["A paragraph."]
    extraction_path = archive.parent / "experiments" / experiment_id / "extraction.json"
    assert json.loads(extraction_path.read_text())

    unavailable = run_step(archive, experiment_id, "draft_text")
    assert unavailable["status"] == "unavailable"


def test_experiment_rejects_non_pdf_and_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="PDF"):
        create_experiment(tmp_path / "archive", "notes.txt", b"text")

    with pytest.raises(ValueError, match="Invalid experiment"):
        read_manifest(tmp_path / "archive", "../escape")
