import io
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import knowledge.experiments.experiment_runner as experiments
import knowledge.experiments.experiment_store as experiment_store
from knowledge.knowledge_domain.application_errors import Conflict
from knowledge.model_integration.prompt_registry import (
    activate_revision,
    get_default,
    save_revision,
    seed_defaults,
)

pytestmark = pytest.mark.usefixtures("poppler_extraction")


def fixture_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=400)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
        }
    )
    content = DecodedStreamObject()
    content.set_data(
        b"BT /F1 12 Tf 30 350 Td (First observation.) Tj 0 -36 Td (Second observation.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


@pytest.fixture
def experiment(tmp_path: Path) -> tuple[Path, str]:
    seed_defaults()
    seed = get_default("recipe", "segment_blocks")
    paragraphs = save_revision(
        "recipe",
        "segment_blocks",
        {
            **seed.payload,
            "parameters": {"mode": "paragraphs", "max_characters": 2000},
        },
        seed.revision,
    )
    activate_revision("recipe", "segment_blocks", paragraphs.revision, seed.revision)
    root = tmp_path / "archive"
    identifier = experiments.create_experiment(root, "reviewed-fixture.pdf", fixture_pdf())
    return root, identifier


def run(experiment: tuple[Path, str], step: str, recipe=None, **kwargs):
    attempt = experiments.prepare_attempt(
        *experiment, step, recipe or get_default("recipe", step), **kwargs
    )
    return experiments.execute_attempt(*experiment, attempt)


def test_real_pdf_and_blocks_use_same_shared_operations_and_exact_references(
    experiment: tuple[Path, str],
):
    assert experiments.read_manifest(*experiment)["steps"] == {}
    extracted = run(experiment, "extract_text")
    assert extracted["status"] == "completed", extracted["error"]
    segmented = run(experiment, "segment_blocks")
    assert segmented["status"] == "completed", segmented["error"]
    assert segmented["inputs"] == {"extract_text": extracted["id"]}
    assert [block["bullets"] for block in segmented["output"]["blocks"]] == [
        ["First observation.\nSecond observation."],
    ]
    for block in segmented["output"]["blocks"]:
        span = block["sources"][0]
        assert span["extraction_revision"] == extracted["output"]["revision"]
        assert (
            extracted["output"]["pages"][span["page"] - 1][span["start"] : span["end"]]
            == span["quote"]
        )
    assert segmented["recipe"]["revision"] == 2
    assert segmented["output_schema_hash"]
    assert "dirty" in segmented["code"]


def test_reruns_retain_results_and_mark_downstream_stale(experiment: tuple[Path, str]):
    original = run(experiment, "extract_text")
    blocks = run(experiment, "segment_blocks")
    repeated = run(experiment, "extract_text")
    history = experiments.read_attempts(*experiment)
    assert [attempt["id"] for attempt in history] == [original["id"], blocks["id"], repeated["id"]]
    assert history[0]["output"] == original["output"]
    assert history[1]["output"] == blocks["output"]
    assert history[1]["stale"] is True
    with pytest.raises(Conflict, match="stale"):
        experiments.prepare_attempt(
            *experiment, "formulate_claims", get_default("recipe", "formulate_claims")
        )
    comparative = run(experiment, "segment_blocks", input_attempts={"extract_text": original["id"]})
    assert comparative["status"] == "completed"
    assert experiments.read_attempts(*experiment)[-1]["stale"] is True


def test_comparison_rejects_mixed_input_lineages(experiment: tuple[Path, str]):
    old = run(experiment, "extract_text")
    blocks = run(experiment, "segment_blocks")
    newer = run(experiment, "extract_text")
    assert old["id"] != newer["id"]
    with pytest.raises(ValueError, match="disagree"):
        experiments.prepare_attempt(
            *experiment,
            "formulate_claims",
            get_default("recipe", "formulate_claims"),
            input_attempts={"extract_text": newer["id"], "segment_blocks": blocks["id"]},
        )


def test_missing_dependency_fails_before_creating_an_attempt(experiment: tuple[Path, str]):
    with pytest.raises(ValueError, match="Run extract_text"):
        experiments.prepare_attempt(
            *experiment, "segment_blocks", get_default("recipe", "segment_blocks")
        )
    assert experiments.read_attempts(*experiment) == []


def test_failed_rerun_retains_success_without_invalidating_downstream(
    experiment: tuple[Path, str], monkeypatch
):
    run(experiment, "extract_text")
    completed = run(experiment, "segment_blocks")
    recipe = get_default("recipe", "segment_blocks")
    payload = {**recipe.payload, "parameters": {"mode": "model", "max_characters": 2000}}
    variant = save_revision("recipe", "segment_blocks", payload, recipe.revision)

    def unavailable_provider(*args, **kwargs):
        raise ValueError("Provider unavailable during test")

    monkeypatch.setattr(
        "knowledge.model_integration.structured_generation.run_hermes", unavailable_provider
    )
    failed = run(experiment, "segment_blocks", variant)
    assert failed["status"] == "failed"
    assert "Provider unavailable" in failed["error"]
    history = experiments.read_attempts(*experiment)
    assert history[1]["id"] == completed["id"]
    assert history[1]["stale"] is False
    assert any(
        event["event"] == "attempt_finished" and event["status"] == "failed"
        for event in experiments.read_attempt_trace(*experiment, failed["id"])
    )


@pytest.mark.parametrize("filename", ["source.pdf", "knowledge.json"])
def test_input_file_changes_fail_before_execution(experiment: tuple[Path, str], filename):
    attempt_id = experiments.prepare_attempt(
        *experiment, "extract_text", get_default("recipe", "extract_text")
    )
    directory = experiment_store.experiment_directory(*experiment)
    if filename == "source.pdf":
        (directory / filename).write_bytes(fixture_pdf() + b"changed")
    else:
        (directory / filename).write_text('{"records": ["modified"]}')
    result = experiments.execute_attempt(*experiment, attempt_id)
    assert result["status"] == "failed"
    assert "snapshot changed" in result["error"]
    assert result["output"] is None


def test_prepared_attempt_keeps_saved_recipe_and_prompt_when_new_draft_is_saved(
    experiment: tuple[Path, str],
):
    recipe = get_default("recipe", "extract_text")
    attempt_id = experiments.prepare_attempt(*experiment, "extract_text", recipe)
    save_revision(
        "recipe", "extract_text", {**recipe.payload, "parameters": {"marker": "new draft"}}, 1
    )
    result = experiments.execute_attempt(*experiment, attempt_id)
    assert result["status"] == "completed", result["error"]
    assert result["recipe"] == recipe.model_dump(mode="json")
    assert result["prompt"]["payload"]["text"]


def test_cancelled_queued_attempt_cannot_generate_a_result(experiment: tuple[Path, str]):
    attempt_id = experiments.prepare_attempt(
        *experiment, "extract_text", get_default("recipe", "extract_text")
    )
    experiments.request_cancel(*experiment, attempt_id)
    result = experiments.execute_attempt(*experiment, attempt_id)
    assert result["status"] == "cancelled"
    assert result["output"] is None
    assert experiments.execute_attempt(*experiment, attempt_id) == result


@pytest.mark.parametrize("cancel", [False, True])
def test_external_extraction_is_terminated_on_step_timeout_or_user_cancellation(
    experiment: tuple[Path, str], monkeypatch, cancel
):
    started = Event()
    processes = []
    real_popen = subprocess.Popen

    def slow_external_operation(arguments, *args, **kwargs):
        if arguments[0] != "pdftotext":
            return real_popen(arguments, *args, **kwargs)
        process = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], *args, **kwargs)
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr(
        "knowledge.document_processing.pdf_text_extraction.subprocess.Popen",
        slow_external_operation,
    )
    original = get_default("recipe", "extract_text")
    configuration = original.payload["model"]
    assert isinstance(configuration, dict)
    payload = {**original.payload, "model": {**configuration, "timeout_seconds": 1}}
    recipe = save_revision("recipe", "extract_text", payload, original.revision)
    attempt_id = experiments.prepare_attempt(*experiment, "extract_text", recipe)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(experiments.execute_attempt, *experiment, attempt_id)
        assert started.wait(timeout=5)
        if cancel:
            experiments.request_cancel(*experiment, attempt_id)
        result = future.result(timeout=5)
    assert result["status"] == ("cancelled" if cancel else "failed")
    assert result["output"] is None
    assert processes[0].poll() is not None
    if not cancel:
        assert "time limit" in result["error"]


def test_worker_lock_blocks_recovery_and_deletion_but_permits_cancellation(
    experiment: tuple[Path, str],
):
    attempt_id = experiments.prepare_attempt(
        *experiment, "extract_text", get_default("recipe", "extract_text")
    )
    with (
        experiment_store.experiment_lock(*experiment),
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        with pytest.raises(Conflict, match="active worker"):
            executor.submit(experiments.delete_experiment, experiment[0], experiment[1]).result()
        with pytest.raises(Conflict, match="active worker"):
            executor.submit(experiments.recover_attempt, *experiment, attempt_id).result()
        executor.submit(experiments.request_cancel, *experiment, attempt_id).result()
    assert experiments.recover_attempt(*experiment, attempt_id)["status"] == "cancelled"


def test_recovery_preserves_abandoned_attempt_and_allows_new_attempt(experiment: tuple[Path, str]):
    attempt_id = experiments.prepare_attempt(
        *experiment, "extract_text", get_default("recipe", "extract_text")
    )
    recovered = experiments.recover_attempt(*experiment, attempt_id)
    assert recovered["status"] == "abandoned"
    assert run(experiment, "extract_text")["status"] == "completed"
    assert experiments.read_attempts(*experiment)[0]["id"] == attempt_id


def test_cleanup_is_isolated_idempotent_and_preserves_saved_recipes(experiment: tuple[Path, str]):
    other = experiments.create_experiment(experiment[0], "other.pdf", fixture_pdf())
    result = run(experiment, "extract_text")
    report = experiments.export_experiment(*experiment)
    experiments.delete_experiment(*experiment)
    experiments.delete_experiment(*experiment)
    assert experiments.read_manifest(experiment[0], other)["filename"] == "other.pdf"
    assert get_default("recipe", "extract_text").revision == 1
    assert report["attempts"][0]["output"] == result["output"]


def test_cleanup_failure_is_reported_and_can_be_retried(experiment: tuple[Path, str], monkeypatch):
    with monkeypatch.context() as failed_filesystem:

        def fail_remove(path):
            (path / "manifest.json").unlink()
            raise PermissionError("fixture filesystem failure")

        failed_filesystem.setattr(
            "knowledge.experiments.experiment_runner.shutil.rmtree", fail_remove
        )
        with pytest.raises(ValueError, match="retry deletion"):
            experiments.delete_experiment(*experiment)
    assert experiments.list_experiments(experiment[0])[0]["status"] == "cleanup_failed"
    assert experiments.read_attempts(*experiment) == []
    experiments.delete_experiment(*experiment)
    assert experiments.list_experiments(experiment[0]) == []


def test_disk_changes_require_restart_before_preparing_or_executing(
    experiment: tuple[Path, str], monkeypatch
):
    recipe = get_default("recipe", "extract_text")
    identifier = experiments.prepare_attempt(*experiment, "extract_text", recipe)
    changed = experiment_store.LOADED_CODE.model_copy(update={"hash": "changed source"})
    monkeypatch.setattr("knowledge.experiments.experiment_store.code_fingerprint", lambda: changed)
    with pytest.raises(Conflict, match="restart the server"):
        experiments.prepare_attempt(*experiment, "extract_text", recipe)
    result = experiments.execute_attempt(*experiment, identifier)
    assert result["status"] == "failed"
    assert "code changed" in result["error"]
    assert result["output"] is None


def test_trace_shows_actual_requests_without_raw_reasoning_or_secret_fields(
    experiment: tuple[Path, str],
):
    attempt = run(experiment, "extract_text")
    trace = (
        experiment_store.experiment_directory(*experiment) / "attempts" / attempt["id"] / "trace"
    )
    trace.mkdir()
    (trace / "request-0.json").write_text(
        json.dumps(
            {
                "instructions": "Summarize the observation",
                "input": "First observation.",
                "api_key": "secret value",
            }
        )
    )
    (trace / "response-0.json").write_text(
        json.dumps(
            {
                "response": "A concise result",
                "reasoning": "private internal thoughts",
                "execution": "simulated",
            }
        )
    )
    (trace / "events.jsonl").write_text(
        json.dumps(
            {
                "time": "2026-09-15T12:00:00Z",
                "event": "model_response",
                "request_file": "request-0.json",
                "response_file": "response-0.json",
            }
        )
        + "\n"
        + '{"partial":'
    )
    events = experiments.read_attempt_trace(*experiment, attempt["id"])
    model = next(event for event in events if event["event"] == "model_response")
    assert model["request"] == {
        "instructions": "Summarize the observation",
        "input": "First observation.",
    }
    assert model["response"] == {"response": "A concise result", "execution": "simulated"}


def test_legacy_run_is_inspectable_and_cannot_be_silently_reexecuted(experiment: tuple[Path, str]):
    manifest = experiment_store.experiment_directory(*experiment) / "manifest.json"
    manifest.write_text(json.dumps({"id": experiment[1], "filename": "legacy.pdf", "steps": {}}))
    assert experiments.read_manifest(*experiment)["legacy"] is True
    assert experiments.export_experiment(*experiment)["manifest"]["filename"] == "legacy.pdf"
    with pytest.raises(ValueError, match="Legacy experiment is read-only"):
        experiments.prepare_attempt(
            *experiment, "extract_text", get_default("recipe", "extract_text")
        )


def test_invalid_sources_and_traversal_are_rejected(tmp_path):
    for filename, content in [("notes.txt", b"text"), ("broken.pdf", b"pdf bytes")]:
        with pytest.raises(ValueError, match="PDF"):
            experiments.create_experiment(tmp_path / "archive", filename, content)
    with pytest.raises(ValueError, match="Invalid experiment"):
        experiments.read_manifest(tmp_path / "archive", "../escape")
