"""Share generation configuration and responses with the standalone Hermes runtime."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"]


class ModelConfiguration(BaseModel):
    """Pin the bounded, tool-free Hermes request configuration."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    model: str | None = Field(default=None, min_length=1)
    provider: str | None = Field(default=None, min_length=1)
    reasoning_effort: ReasoningEffort = "max"
    max_attempts: int = Field(default=2, ge=1, le=2)
    timeout_seconds: float = Field(default=240, ge=1, le=240)
    allowed_tools: list[str] = Field(default_factory=list)
    cost_limit_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def reject_unsupported_capabilities(self) -> Self:
        """Reject limits or capabilities that the adapter cannot enforce."""
        if self.allowed_tools:
            raise ValueError("This Hermes adapter does not support tool execution")
        if self.cost_limit_usd is not None:
            raise ValueError("This Hermes adapter cannot enforce a monetary cost limit")
        return self

    def resolved(self) -> "ModelConfiguration":
        """Make the existing Luna defaults explicit before hashing a request."""
        return self.model_copy(
            update={
                "model": self.model or "gpt-5.6-luna",
                "provider": self.provider or "openai-codex",
            }
        )


class GenerationResponse(BaseModel):
    """Retain response text and optional provenance from the Hermes bridge."""

    response: str
    execution: str = "unverified"
    model: str | None = None
    provider: str | None = None

    requested_model: str | None = None
    requested_provider: str | None = None
    session_id: str | None = None
