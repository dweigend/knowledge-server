"""Describe dictionary projections of validated experiment documents."""

from typing import NotRequired, TypedDict

from pydantic import JsonValue


class AttemptView(TypedDict):
    """Combine pinned inputs and optional execution details without changing stored formats."""

    id: str
    step: str
    created_at: str
    recipe: dict[str, JsonValue]
    prompt: dict[str, JsonValue]
    author_rules: dict[str, JsonValue] | None
    inputs: dict[str, str]
    input_hashes: dict[str, str]
    explicit_inputs: bool
    source_hash: str
    knowledge_hash: str
    code: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    output_schema_hash: str
    status: str
    output: dict[str, JsonValue] | None
    error: str | None
    duration_seconds: float | None
    cancel_requested: bool
    started_at: NotRequired[str | None]
    finished_at: NotRequired[str]
    worker_pid: NotRequired[int]
    output_hash: NotRequired[str | None]
    stale: NotRequired[bool]
    stale_reason: NotRequired[str]
    events: NotRequired[list[dict[str, JsonValue]]]


class ExperimentView(TypedDict):
    """Expose a manifest with the latest attempt for each pipeline step."""

    version: int
    id: str
    filename: str
    created_at: str
    source_hash: str
    knowledge_hash: str
    steps: dict[str, AttemptView]
    status: str


class ExperimentReport(TypedDict):
    """Export a manifest and its ordered attempt history."""

    manifest: ExperimentView
    attempts: list[AttemptView]
