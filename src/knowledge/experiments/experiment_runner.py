"""Manage the full lifecycle of manual pipeline experiments.

Experiments pin every input, isolate attempts, support cancellation and recovery,
and never accept results into canonical knowledge implicitly.
"""

import hashlib
import json
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from knowledge.experiments import (
    experiment_models,
    experiment_step_catalog,
    experiment_store,
    pipeline_specification,
)
from knowledge.knowledge_domain import application_errors, knowledge_record_models
from knowledge.model_integration import prompt_registry
from knowledge.runtime_support import atomic_json_files

MAX_PDF_BYTES = 64 * 1024 * 1024


def create_experiment(
    archive_root: Path,
    filename: str,
    content: bytes,
    seed_records: list[knowledge_record_models.Record] | None = None,
) -> str:
    """Copy one PDF and explicitly supplied knowledge into a private experiment."""
    if not filename.lower().endswith(".pdf") or not content.startswith(b"%PDF-"):
        raise ValueError("Experiment sources must contain a PDF header and use a .pdf filename")
    if len(content) > MAX_PDF_BYTES:
        raise ValueError("Experiment PDFs must not exceed 64 MiB")
    records = [record.model_dump(mode="json") for record in seed_records or []]
    experiment_id = uuid4().hex
    with experiment_store.experiment_lock(archive_root, experiment_id):
        directory = experiment_store.experiments_root(archive_root) / experiment_id
        directory.mkdir(mode=0o700)
        (directory / "source.pdf").write_bytes(content)
        manifest = experiment_models.ExperimentManifest(
            id=experiment_id,
            filename=Path(filename).name,
            created_at=experiment_store.now(),
            source_hash=hashlib.sha256(content).hexdigest(),
            knowledge_hash=experiment_store.content_hash(records),
        )
        atomic_json_files.write_json_atomically(directory / "knowledge.json", {"records": records})
        atomic_json_files.write_json_atomically(
            directory / "manifest.json", manifest.model_dump(mode="json")
        )
    return experiment_id


def read_attempts(archive_root: Path, experiment_id: str) -> list[dict]:
    """Read history and derive stale inputs against the latest successful attempts."""
    directory = experiment_store.experiment_directory(archive_root, experiment_id)
    experiment_store.read_experiment(directory)
    attempts = sorted(
        (
            experiment_store.read_attempt(path.parent)
            for path in (directory / "attempts").glob("*/inputs.json")
        ),
        key=lambda attempt: (attempt["created_at"], attempt["id"]),
    )
    latest = {
        attempt["step"]: attempt["id"] for attempt in attempts if attempt["status"] == "completed"
    }
    indexed = {attempt["id"]: attempt for attempt in attempts}
    for attempt in attempts:
        reasons = []
        for step, identifier in attempt["inputs"].items():
            parent = indexed.get(identifier)
            if parent is None or parent["status"] != "completed":
                reasons.append(f"Missing successful input for {step}")
            elif latest.get(step) != identifier or parent.get("stale", False):
                reasons.append(f"Newer successful input available for {step}")
        attempt["stale"] = bool(reasons)
        attempt["stale_reason"] = "; ".join(reasons)
    return attempts


def read_manifest(archive_root: Path, experiment_id: str) -> dict:
    """Read one current experiment with its latest step statuses."""
    directory = experiment_store.experiment_directory(archive_root, experiment_id)
    manifest = experiment_store.read_experiment(directory).model_dump(mode="json")
    attempts = read_attempts(archive_root, experiment_id)
    manifest["steps"] = {attempt["step"]: attempt for attempt in attempts}
    manifest["status"] = attempts[-1]["status"] if attempts else "created"
    return manifest


def list_experiments(archive_root: Path) -> list[dict]:
    """List private sources with their latest manually requested step status."""
    root = experiment_store.experiments_root(archive_root)
    if not root.exists():
        return []
    manifests = []
    for path in root.iterdir():
        manifest_path = path / "manifest.json"
        if (
            path.name.startswith(".")
            or path.is_symlink()
            or not path.is_dir()
            or not manifest_path.exists()
        ):
            continue
        if json.loads(manifest_path.read_text()).get("version") != 2:
            continue
        manifests.append(read_manifest(archive_root, path.name))
    return sorted(
        manifests,
        key=lambda manifest: manifest["created_at"],
        reverse=True,
    )


def _select_inputs(
    attempts: list[dict],
    dependencies: tuple[str, ...],
    supplied: dict[str, str] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    selected = (
        supplied
        if supplied is not None
        else {
            attempt["step"]: attempt["id"]
            for attempt in attempts
            if attempt["status"] == "completed"
        }
    )
    if supplied is not None and set(supplied) != set(dependencies):
        raise ValueError("Explicit input attempts must match the step's required dependencies")
    indexed = {attempt["id"]: attempt for attempt in attempts}
    pins, hashes = {}, {}
    for step in dependencies:
        attempt = indexed.get(selected.get(step, ""))
        if attempt is None or attempt["step"] != step or attempt["status"] != "completed":
            raise ValueError(f"Run {step} successfully before starting this step")
        if attempt["stale"] and supplied is None:
            raise application_errors.Conflict(
                f"Input {step} is stale; rerun it or explicitly select comparison inputs"
            )
        pins[step], hashes[step] = attempt["id"], attempt["output_hash"]
    _validate_input_lineage(pins, indexed)
    return pins, hashes


def _validate_input_lineage(pins: dict[str, str], indexed: dict[str, dict]) -> None:
    lineage: dict[str, str] = {}
    pending = list(pins.items())
    while pending:
        step, identifier = pending.pop()
        if step in lineage:
            if lineage[step] != identifier:
                raise ValueError(f"Selected input attempts disagree on the revision of {step}")
            continue
        lineage[step] = identifier
        attempt = indexed.get(identifier)
        if attempt is None or attempt["status"] != "completed":
            raise ValueError(f"Selected input lineage has no successful result for {step}")
        pending.extend(attempt["inputs"].items())


def prepare_attempt(
    archive_root: Path,
    experiment_id: str,
    step: str,
    recipe: prompt_registry.ConfigRevision,
    input_attempts: dict[str, str] | None = None,
) -> str:
    """Pin a manual attempt without making model requests or advancing dependencies."""
    definition = experiment_step_catalog.get_step_definition(step)
    if recipe.kind != "recipe" or recipe.hash != prompt_registry.payload_hash(recipe.payload):
        raise ValueError("Attempt requires an intact saved recipe revision")
    parsed = prompt_registry.Recipe.model_validate(recipe.payload)
    definition.validate_recipe(parsed)
    fingerprint = experiment_store.code_fingerprint()
    if fingerprint.hash != experiment_store.LOADED_CODE.hash:
        raise application_errors.Conflict(
            "Application files changed; restart the server before preparing an attempt"
        )
    if parsed.step != step:
        raise ValueError("Recipe belongs to a different pipeline step")
    saved, _, prompt, author_rules = prompt_registry.resolve_recipe(recipe.name, recipe.revision)
    if saved != recipe:
        raise ValueError("Recipe differs from its saved immutable revision")
    with experiment_store.experiment_lock(archive_root, experiment_id):
        directory = experiment_store.experiment_directory(archive_root, experiment_id)
        manifest = experiment_store.read_experiment(directory)
        attempts = read_attempts(archive_root, experiment_id)
        if any(attempt["status"] in {"queued", "running"} for attempt in attempts):
            raise application_errors.Conflict(
                "Finish, cancel or recover the pending attempt before preparing another"
            )
        pins, hashes = _select_inputs(attempts, definition.dependencies, input_attempts)
        schema = definition.output_contract.model_json_schema()
        specification = experiment_models.AttemptInputs(
            id=uuid4().hex,
            step=step,
            created_at=experiment_store.now(),
            recipe=recipe,
            prompt=prompt,
            author_rules=author_rules,
            inputs=pins,
            input_hashes=hashes,
            explicit_inputs=input_attempts is not None,
            source_hash=manifest.source_hash,
            knowledge_hash=manifest.knowledge_hash,
            code=fingerprint,
            output_schema=schema,
            output_schema_hash=experiment_store.content_hash(schema),
        )
        atomic_json_files.write_json_atomically(
            directory / "attempts" / specification.id / "inputs.json",
            specification.model_dump(mode="json"),
        )
    return specification.id


def _execution_inputs(
    directory: Path, specification: experiment_models.AttemptInputs
) -> tuple[dict, list[knowledge_record_models.Record]]:
    source_hash = hashlib.sha256((directory / "source.pdf").read_bytes()).hexdigest()
    records = json.loads((directory / "knowledge.json").read_text())["records"]
    if (
        source_hash != specification.source_hash
        or experiment_store.content_hash(records) != specification.knowledge_hash
    ):
        raise ValueError("Experiment source or knowledge snapshot changed after it was pinned")
    inputs = {}
    for step, identifier in specification.inputs.items():
        attempt = experiment_store.read_attempt(
            experiment_store.attempt_directory(directory, identifier)
        )
        if (
            attempt["status"] != "completed"
            or attempt["output_hash"] != specification.input_hashes[step]
        ):
            raise ValueError(f"Pinned {step} output changed or is no longer available")
        inputs[step] = attempt["output"]
    return inputs, [knowledge_record_models.Record.model_validate(record) for record in records]


def _attempt_cancellation(path: Path, started: float, timeout_seconds: float) -> Callable[[], bool]:
    def cancelled() -> bool:
        if time.monotonic() - started >= timeout_seconds:
            raise TimeoutError("Experiment step exceeded its total wall-clock time limit")
        return (path / "cancel.json").exists()

    return cancelled


def _perform_attempt(
    directory: Path,
    path: Path,
    specification: experiment_models.AttemptInputs,
    started: float,
) -> dict:
    recipe = prompt_registry.Recipe.model_validate(specification.recipe.payload)
    cancelled = _attempt_cancellation(path, started, recipe.model.timeout_seconds)
    if cancelled():
        raise InterruptedError("Attempt cancelled before execution")
    if (
        specification.code.hash != experiment_store.code_fingerprint().hash
        or specification.code.hash != experiment_store.LOADED_CODE.hash
    ):
        raise ValueError("Application code changed; prepare a new attempt with the current code")
    definition = experiment_step_catalog.get_step_definition(specification.step)
    contract = definition.output_contract
    if specification.output_schema_hash != experiment_store.content_hash(
        contract.model_json_schema()
    ):
        raise ValueError("Output schema changed; prepare a new attempt")
    saved, _, prompt, rules = prompt_registry.resolve_recipe(
        specification.recipe.name, specification.recipe.revision
    )
    if (
        saved != specification.recipe
        or prompt != specification.prompt
        or rules != specification.author_rules
    ):
        raise ValueError("Pinned configuration no longer matches the immutable registry")
    inputs, knowledge = _execution_inputs(directory, specification)
    result = definition.execute(
        pipeline_specification.StepExecution(
            pdf=directory / "source.pdf",
            inputs=inputs,
            knowledge=knowledge,
            recipe=recipe,
            prompt_text=prompt_registry.Prompt.model_validate(prompt.payload).text,
            author_rules=rules.payload if rules is not None else None,
            output_directory=path / "trace",
            cancelled=cancelled,
        )
    )
    if cancelled():
        raise InterruptedError("Attempt cancelled; generated result was not accepted")
    return contract.model_validate(result.model_dump()).model_dump(mode="json")


def execute_attempt(archive_root: Path, experiment_id: str, attempt_id: str) -> dict:
    """Execute one pinned attempt while excluding concurrent workers and deletion."""
    with experiment_store.experiment_lock(archive_root, experiment_id):
        directory = experiment_store.experiment_directory(archive_root, experiment_id)
        path = experiment_store.attempt_directory(directory, attempt_id)
        if (path / "result.json").exists():
            return experiment_store.read_attempt(path)
        if (path / "state.json").exists():
            raise application_errors.Conflict(
                "Interrupted attempt must be recovered before another execution"
            )
        specification = experiment_models.AttemptInputs.model_validate_json(
            (path / "inputs.json").read_text()
        )
        state = experiment_models.AttemptState(
            started_at=experiment_store.now(), worker_pid=os.getpid()
        )
        atomic_json_files.write_json_atomically(path / "state.json", state.model_dump(mode="json"))
        started = time.monotonic()
        output, error, status = None, None, "failed"
        try:
            output = _perform_attempt(directory, path, specification, started)
            status = "completed"
        except InterruptedError as failure:
            status, error = "cancelled", str(failure)
        except Exception as failure:
            status, error = "failed", str(failure)
        terminal = experiment_models.AttemptResult(
            status=status,
            started_at=state.started_at,
            finished_at=experiment_store.now(),
            duration_seconds=time.monotonic() - started,
            output=output,
            output_hash=experiment_store.content_hash(output) if output is not None else None,
            error=error,
        )
        experiment_store.append_result(path, terminal)
        return experiment_store.read_attempt(path)


def request_cancel(archive_root: Path, experiment_id: str, attempt_id: str) -> None:
    """Signal a worker through an independent marker without waiting on its lock."""
    directory = experiment_store.experiment_directory(archive_root, experiment_id)
    path = experiment_store.attempt_directory(directory, attempt_id)
    if (path / "result.json").exists():
        raise application_errors.Conflict("Completed attempts cannot be cancelled")
    try:
        with (path / "cancel.json").open("x") as stream:
            json.dump({"requested_at": experiment_store.now()}, stream)
    except FileExistsError:
        pass


def recover_attempt(archive_root: Path, experiment_id: str, attempt_id: str) -> dict:
    """Mark interruption only after a worker released the operating-system lock."""
    with experiment_store.experiment_lock(archive_root, experiment_id):
        directory = experiment_store.experiment_directory(archive_root, experiment_id)
        path = experiment_store.attempt_directory(directory, attempt_id)
        attempt = experiment_store.read_attempt(path)
        if attempt["status"] not in {"queued", "running"}:
            return attempt
        cancelled = (path / "cancel.json").exists()
        experiment_store.append_result(
            path,
            experiment_models.AttemptResult(
                status="cancelled" if cancelled else "abandoned",
                started_at=attempt.get("started_at"),
                finished_at=experiment_store.now(),
                duration_seconds=0,
                error="Worker interrupted; prepare a new attempt with the same pinned inputs",
            ),
        )
        return experiment_store.read_attempt(path)


def delete_experiment(archive_root: Path, experiment_id: str) -> None:
    """Remove one idle experiment directory."""
    experiment_store.validate_id(experiment_id)
    with experiment_store.experiment_lock(archive_root, experiment_id):
        directory = experiment_store.experiments_root(archive_root) / experiment_id
        if not directory.exists():
            return
        shutil.rmtree(experiment_store.experiment_directory(archive_root, experiment_id))


def read_attempt_trace(archive_root: Path, experiment_id: str, attempt_id: str) -> list[dict]:
    """Read structured execution events without exposing raw process transcripts."""
    path = experiment_store.attempt_directory(
        experiment_store.experiment_directory(archive_root, experiment_id), attempt_id
    )
    attempt = experiment_store.read_attempt(path)
    events = [
        {"time": attempt["created_at"], "event": "attempt_prepared", "attempt_id": attempt_id}
    ]
    if attempt.get("started_at"):
        events.append(
            {
                "time": attempt["started_at"],
                "event": "attempt_started",
                "worker_pid": attempt["worker_pid"],
            }
        )
    for file in sorted(path.rglob("events.jsonl")):
        content = file.read_text()
        lines = content.split("\n")[:-1]
        for line in lines:
            if line.strip():
                events.append(_trace_event(file.parent, json.loads(line)))
    if attempt.get("finished_at"):
        events.append(
            {
                "time": attempt["finished_at"],
                "event": "attempt_finished",
                "status": attempt["status"],
                "error": attempt["error"],
                "duration_seconds": attempt["duration_seconds"],
            }
        )
    return sorted(events, key=lambda event: event.get("time", ""))


def _trace_event(directory: Path, event: dict) -> dict:
    fields = {
        "request_file": ("instructions", "input", "configuration"),
        "response_file": ("response", "model", "provider", "execution"),
    }
    for reference, allowed in fields.items():
        filename = event.get(reference)
        if not isinstance(filename, str) or Path(filename).name != filename:
            continue
        path = directory / filename
        if path.is_symlink() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        event[reference.removesuffix("_file")] = {
            key: payload[key] for key in allowed if key in payload
        }
    return event


def export_experiment(archive_root: Path, experiment_id: str) -> dict:
    """Return an explicitly requested private report without writing repository files."""
    manifest = read_manifest(archive_root, experiment_id)
    attempts = read_attempts(archive_root, experiment_id)
    for attempt in attempts:
        attempt["events"] = read_attempt_trace(archive_root, experiment_id, attempt["id"])
    return {"manifest": manifest, "attempts": attempts}
