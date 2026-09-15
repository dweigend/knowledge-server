import json

import pytest
from test_pipeline_steps import write_reviewed_pdf

from knowledge.experiment_cli import main
from knowledge.experimentation import prepare_attempt
from knowledge.prompt_registry import get_revision, save_revision


def invoke(capsys, root, *arguments):
    status = main(["--archive-root", str(root), *arguments])
    result = json.loads(capsys.readouterr().out)
    assert status == 0
    return result


def test_cli_runs_and_inspects_same_private_attempts_without_database(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.delenv("KNOWLEDGE_DATABASE_URL", raising=False)
    pdf = tmp_path / "fixture.pdf"
    write_reviewed_pdf(pdf)
    root = tmp_path / "archive"
    identifier = invoke(capsys, root, "create", str(pdf))["experiment_id"]
    extraction = invoke(capsys, root, "run", identifier, "extract_text")
    assert extraction["output"]["pages"][0].strip() == "Group A scored higher."
    recipe = get_revision("recipe", "segment_blocks")
    payload = recipe.payload | {"parameters": {"mode": "paragraphs", "max_characters": 2000}}
    saved = save_revision("recipe", "segment_blocks", payload, recipe.revision)
    blocks = invoke(
        capsys, root, "run", identifier, "segment_blocks", "--revision", str(saved.revision)
    )
    assert blocks["inputs"] == {"extract_text": extraction["id"]}
    assert blocks["output"]["blocks"][0]["sources"][0]["quote"] == "Group A scored higher."
    read = invoke(capsys, root, "inspect", identifier)
    assert [attempt["id"] for attempt in read["attempts"]] == [extraction["id"], blocks["id"]]
    report = tmp_path / "private-report.json"
    invoke(capsys, root, "export", identifier, "--output", str(report))
    assert json.loads(report.read_text())["manifest"]["id"] == identifier
    assert report.stat().st_mode & 0o777 == 0o600
    invoke(capsys, root, "delete", identifier)
    assert invoke(capsys, root, "inspect") == []
    assert get_revision("recipe", "segment_blocks").revision == saved.revision
    assert report.exists()


def test_cli_cancel_and_recover_share_attempt_state(tmp_path, capsys):
    pdf = tmp_path / "fixture.pdf"
    write_reviewed_pdf(pdf)
    root = tmp_path / "archive"
    identifier = invoke(capsys, root, "create", str(pdf))["experiment_id"]
    attempt = prepare_attempt(
        root, identifier, "extract_text", get_revision("recipe", "extract_text")
    )
    invoke(capsys, root, "cancel", identifier, attempt)
    recovered = invoke(capsys, root, "recover", identifier, attempt)
    assert recovered["status"] == "cancelled"


def test_export_does_not_replace_existing_file(tmp_path, capsys):
    pdf = tmp_path / "fixture.pdf"
    write_reviewed_pdf(pdf)
    identifier = invoke(capsys, tmp_path / "archive", "create", str(pdf))["experiment_id"]
    report = tmp_path / "existing.json"
    report.write_text("Keep me")
    with pytest.raises(SystemExit) as error:
        main(
            [
                "--archive-root",
                str(tmp_path / "archive"),
                "export",
                identifier,
                "--output",
                str(report),
            ]
        )
    assert error.value.code == 2
    assert report.read_text() == "Keep me"
