"""Validate the parameters consumed by individual pipeline operations."""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class SegmentationParameters(BaseModel):
    """Select verbatim or model segmentation and bound the block character count."""

    model_config = ConfigDict(strict=True)
    mode: Literal["paragraphs", "model"] = "paragraphs"
    max_characters: int = Field(default=2000, ge=1, le=120000)


class RetrievalParameters(BaseModel):
    """Bound knowledge retrieval while sharing its optional selection query."""

    model_config = ConfigDict(strict=True)
    query: str | None = None
    limit: int = Field(default=20, ge=1, le=40)


OPTIONAL_TEXT: Final[TypeAdapter[str | None]] = TypeAdapter(
    str | None, config=ConfigDict(strict=True)
)
