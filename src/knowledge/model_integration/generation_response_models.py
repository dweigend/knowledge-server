"""Validate cached model responses without changing prompt schemas."""

from pydantic import BaseModel


class GenerationResponse(BaseModel):
    """Retain response text and optional provenance from the Hermes bridge."""

    response: str
    execution: str = "unverified"
    model: str | None = None
    provider: str | None = None


class ActiveRevision(BaseModel):
    """Identify the explicitly activated configuration revision."""

    revision: int
