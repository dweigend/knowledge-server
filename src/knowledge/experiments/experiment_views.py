"""Describe validated projections of stored experiment documents."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ExperimentContract(BaseModel):
    """Reject unknown fields in stored experiment projections."""

    model_config = ConfigDict(extra="forbid")


class TraceEvent(BaseModel):
    """Validate shared event identity while retaining event-specific details."""

    model_config = ConfigDict(extra="allow")

    time: str
    event: str


class AttemptView(ExperimentContract):
    """Combine pinned inputs and optional execution details."""

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
    status: Literal["queued", "running", "completed", "failed", "cancelled", "abandoned"]
    output: dict[str, JsonValue] | None
    error: str | None
    duration_seconds: float | None
    cancel_requested: bool
    started_at: str | None = None
    finished_at: str | None = None
    worker_pid: int | None = None
    output_hash: str | None = None
    stale: bool = False
    stale_reason: str = ""
    events: list[TraceEvent] = Field(default_factory=list)


class ExperimentView(ExperimentContract):
    """Expose a manifest with the latest attempt for each pipeline step."""

    version: int
    id: str
    filename: str
    created_at: str
    source_hash: str
    knowledge_hash: str
    steps: dict[str, AttemptView]
    status: str


class ExperimentReport(ExperimentContract):
    """Export a manifest and its ordered attempt history."""

    manifest: ExperimentView
    attempts: list[AttemptView]
