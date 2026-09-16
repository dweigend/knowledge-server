"""Validate the parameters consumed by individual pipeline operations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SegmentationParameters(BaseModel):
    """Select verbatim or model segmentation and bound the block character count."""

    model_config = ConfigDict(strict=True)
    mode: Literal["paragraphs", "model"] = "paragraphs"
    max_characters: int = Field(default=2000, ge=1, le=120000)


class SelectionParameters(BaseModel):
    """Provide an optional explicit query for source knowledge selection."""

    model_config = ConfigDict(strict=True)
    query: str | None = None


class RetrievalParameters(SelectionParameters):
    """Bound knowledge retrieval while sharing its optional selection query."""

    limit: int = Field(default=20, ge=1, le=40)


class WritingParameters(BaseModel):
    """Provide the optional editorial goal for grounded writing."""

    model_config = ConfigDict(strict=True)
    goal: str | None = None
