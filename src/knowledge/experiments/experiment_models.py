"""Define immutable experiment inputs, lineage, state, and outcomes.

The contracts pin documents, configurations, code fingerprints, and upstream
attempts for reproducible execution.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from knowledge.model_integration import prompt_registry


class ExperimentDocument(BaseModel):
    """Reject unknown persisted experiment fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CodeFingerprint(ExperimentDocument):
    """Identify package contents and the checkout used to prepare an attempt."""

    commit: str | None
    dirty: bool
    hash: str


class ExperimentManifest(ExperimentDocument):
    """Pin one private PDF and a fixed snapshot of existing knowledge."""

    version: Literal[2] = 2
    id: str
    filename: str
    created_at: str
    source_hash: str
    knowledge_hash: str


class AttemptInputs(ExperimentDocument):
    """Pin the complete configuration and inputs before execution starts."""

    id: str
    step: str
    created_at: str
    recipe: prompt_registry.ConfigRevision
    prompt: prompt_registry.ConfigRevision
    author_rules: prompt_registry.ConfigRevision | None
    inputs: dict[str, str]
    input_hashes: dict[str, str]
    explicit_inputs: bool
    source_hash: str
    knowledge_hash: str
    code: CodeFingerprint
    output_schema: dict[str, JsonValue]
    output_schema_hash: str


class AttemptState(ExperimentDocument):
    """Record the worker that owns a nonterminal execution."""

    status: Literal["running"] = "running"
    started_at: str
    worker_pid: int


class AttemptResult(ExperimentDocument):
    """Retain one terminal outcome without replacing an earlier attempt."""

    status: Literal["completed", "failed", "cancelled", "abandoned"]
    started_at: str | None
    finished_at: str
    duration_seconds: float = Field(ge=0)
    output: dict[str, JsonValue] | None = None
    output_hash: str | None = None
    error: str | None = None
