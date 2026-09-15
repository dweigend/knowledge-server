"""Persist private experiment snapshots with atomic files and process-safe locks."""

import fcntl
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from knowledge.experiment_contracts import (
    AttemptInputs,
    AttemptResult,
    AttemptState,
    CodeFingerprint,
    ExperimentManifest,
)
from knowledge.prompt_registry import atomic_json
from knowledge.storage import Conflict, Missing


def now() -> str:
    """Return a sortable UTC timestamp for persisted execution records."""
    return datetime.now(UTC).isoformat()


def content_hash(content: object) -> str:
    """Hash canonical JSON while preserving source whitespace."""
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def experiments_root(archive_root: Path) -> Path:
    """Resolve private experiment storage beside the archive."""
    return archive_root.parent / "experiments"


def validate_id(identifier: str) -> None:
    """Reject identifiers that are not generated lowercase hexadecimal UUIDs."""
    if not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise ValueError("Invalid experiment or attempt id")


def experiment_directory(archive_root: Path, experiment_id: str) -> Path:
    """Resolve one existing experiment without following directory aliases."""
    validate_id(experiment_id)
    root = experiments_root(archive_root).resolve()
    directory = root / experiment_id
    if directory.is_symlink() or not directory.is_dir():
        raise Missing("Experiment does not exist")
    return directory


@contextmanager
def experiment_lock(archive_root: Path, experiment_id: str) -> Iterator[None]:
    """Exclude execution, recovery and deletion without waiting on a worker."""
    validate_id(experiment_id)
    locks = experiments_root(archive_root) / ".locks"
    locks.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (locks / experiment_id).open("a") as stream:
        os.chmod(stream.name, 0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Conflict(
                "Experiment has an active worker; cancel it and wait before retrying"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def read_experiment(directory: Path) -> ExperimentManifest:
    """Read the supported manifest or explain how to preserve a legacy run."""
    payload = json.loads((directory / "manifest.json").read_text())
    if payload.get("version") != 2:
        raise ValueError("Legacy experiment is read-only; export its files and create a new run")
    return ExperimentManifest.model_validate(payload)


def attempt_directory(directory: Path, attempt_id: str) -> Path:
    """Resolve an existing attempt without allowing path traversal or aliases."""
    validate_id(attempt_id)
    path = directory / "attempts" / attempt_id
    if path.is_symlink() or not path.is_dir():
        raise Missing("Experiment attempt does not exist")
    return path


def read_attempt(path: Path) -> dict:
    """Combine immutable inputs and a terminal result for inspection."""
    inputs = AttemptInputs.model_validate_json((path / "inputs.json").read_text())
    result = inputs.model_dump(mode="json")
    result.update(status="queued", output=None, error=None, duration_seconds=None)
    if (path / "state.json").exists():
        state = AttemptState.model_validate_json((path / "state.json").read_text())
        result.update(state.model_dump(mode="json"))
    if (path / "result.json").exists():
        terminal = AttemptResult.model_validate_json((path / "result.json").read_text())
        if terminal.output is not None and terminal.output_hash != content_hash(terminal.output):
            raise ValueError("Attempt output hash does not match its persisted result")
        result.update(terminal.model_dump(mode="json"))
    result["cancel_requested"] = (path / "cancel.json").exists()
    return result


def append_result(path: Path, result: AttemptResult) -> None:
    """Write a terminal outcome once while the caller owns the experiment lock."""
    if (path / "result.json").exists():
        raise Conflict("Attempt already has an immutable terminal result")
    atomic_json(path / "result.json", result.model_dump(mode="json"))


def code_fingerprint() -> CodeFingerprint:
    """Hash application sources, including dirty and untracked package changes."""
    package = Path(__file__).parent
    digest = hashlib.sha256()
    paths = sorted(
        path
        for path in package.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".html", ".css", ".md"}
        and "pdfjs" not in path.parts
    )
    for path in paths:
        digest.update(str(path.relative_to(package)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    repository = package.parents[1]
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return CodeFingerprint(commit=None, dirty=True, hash=digest.hexdigest())
    return CodeFingerprint(commit=commit, dirty=bool(status), hash=digest.hexdigest())


LOADED_CODE = code_fingerprint()
