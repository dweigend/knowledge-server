"""Keep private prompt, recipe and author-rule revisions with explicit activation."""

import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from knowledge.storage import Conflict, Missing

ConfigKind = Literal["prompt", "recipe", "author_rules"]
KINDS = ("prompt", "recipe", "author_rules")
PACKAGED_PROMPTS = ("import", "reconcile", "grounding", "consolidate", "compare", "assess")


class ConfigRevision(BaseModel):
    """Identify immutable configuration content independently of its active default."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: ConfigKind
    name: str
    revision: int = Field(ge=1)
    payload: dict[str, JsonValue]
    hash: str


def configuration_root() -> Path:
    """Resolve the private configuration directory without writing repository files."""
    return Path(
        os.environ.get(
            "KNOWLEDGE_CONFIGURATION_ROOT", "~/.local/share/knowledge-server/configuration"
        )
    ).expanduser()


@contextmanager
def registry_lock() -> Iterator[Path]:
    """Serialize revision creation, activation and first-use seeding."""
    root = configuration_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".lock").open("a") as lock:
        os.chmod(root / ".lock", 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield root


def configuration_directory(root: Path, kind: ConfigKind, name: str) -> Path:
    """Reject configuration identifiers that could escape their private directory."""
    if kind not in KINDS or not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", name):
        raise ValueError("Invalid configuration kind or name")
    return root / kind / name


def atomic_json(path: Path, content: dict) -> None:
    """Publish a complete private JSON file and flush its directory entry."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(content, output, ensure_ascii=False, sort_keys=True, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def latest_revision(directory: Path) -> int:
    """Find the highest durable revision without relying on the active pointer."""
    return max((int(path.stem) for path in directory.glob("[0-9]*.json")), default=0)


def read_revision(directory: Path, revision: int) -> ConfigRevision:
    """Read an existing immutable revision and verify its content hash."""
    path = directory / f"{revision}.json"
    if not path.exists():
        raise Missing("Configuration revision does not exist")
    record = ConfigRevision.model_validate_json(path.read_text())
    if record.hash != payload_hash(record.payload):
        raise ValueError("Configuration revision hash does not match its payload")
    return record


def payload_hash(payload: dict[str, JsonValue]) -> str:
    """Hash canonical JSON content while preserving exact prompt text."""
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def append_revision(
    directory: Path,
    kind: ConfigKind,
    name: str,
    payload: dict[str, JsonValue],
    expected_revision: int,
) -> ConfigRevision:
    """Append one revision after checking the caller's last observed revision."""
    current = latest_revision(directory)
    if current != expected_revision:
        raise Conflict(f"Configuration changed: expected {expected_revision}, found {current}")
    if kind == "prompt" and (not isinstance(payload.get("text"), str) or not payload["text"]):
        raise ValueError("Prompt payload requires nonempty text")
    record = ConfigRevision(
        kind=kind, name=name, revision=current + 1, payload=payload, hash=payload_hash(payload)
    )
    atomic_json(directory / f"{record.revision}.json", record.model_dump(mode="json"))
    return record


def save_revision(
    kind: ConfigKind, name: str, payload: dict[str, JsonValue], expected_revision: int
) -> ConfigRevision:
    """Save a draft revision using zero for a configuration that does not exist."""
    with registry_lock() as root:
        directory = configuration_directory(root, kind, name)
        return append_revision(directory, kind, name, payload, expected_revision)


def get_revision(kind: ConfigKind, name: str, revision: int | None = None) -> ConfigRevision:
    """Read a pinned revision or the latest saved draft when no revision is supplied."""
    with registry_lock() as root:
        directory = configuration_directory(root, kind, name)
        return read_revision(
            directory, revision if revision is not None else latest_revision(directory)
        )


def active_revision(directory: Path) -> int:
    """Read the active revision number, using zero before first activation."""
    path = directory / "active.json"
    return json.loads(path.read_text())["revision"] if path.exists() else 0


def activate_revision(
    kind: ConfigKind, name: str, revision: int, expected_revision: int
) -> ConfigRevision:
    """Activate a saved revision after checking the previously active revision."""
    with registry_lock() as root:
        directory = configuration_directory(root, kind, name)
        current = active_revision(directory)
        if current != expected_revision:
            raise Conflict(
                f"Active configuration changed: expected {expected_revision}, found {current}"
            )
        record = read_revision(directory, revision)
        atomic_json(directory / "active.json", {"revision": revision})
        return record


def get_default(kind: ConfigKind, name: str) -> ConfigRevision:
    """Read the explicitly active configuration without falling back to a draft."""
    with registry_lock() as root:
        directory = configuration_directory(root, kind, name)
        return read_revision(directory, active_revision(directory))


def list_configurations(kind: ConfigKind | None = None) -> list[ConfigRevision]:
    """List the latest saved revision of each configuration in name order."""
    if kind is not None and kind not in KINDS:
        raise ValueError("Invalid configuration kind")
    with registry_lock() as root:
        revisions = []
        for selected in (kind,) if kind else KINDS:
            for directory in sorted((root / selected).glob("*")):
                if directory.is_dir() and latest_revision(directory):
                    revisions.append(read_revision(directory, latest_revision(directory)))
        return revisions


def load_prompt(name: str) -> str:
    """Resolve an active prompt, seeding its packaged default only on first use."""
    with registry_lock() as root:
        directory = configuration_directory(root, "prompt", name)
        if latest_revision(directory) == 0:
            if name not in PACKAGED_PROMPTS:
                raise Missing("No packaged default exists for this prompt")
            text = (Path(__file__).with_name("prompts") / f"{name}.md").read_text()
            append_revision(directory, "prompt", name, {"text": text}, 0)
            atomic_json(directory / "active.json", {"revision": 1})
        prompt = read_revision(directory, active_revision(directory))
        text = prompt.payload.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError("Active prompt does not contain text")
        return text
