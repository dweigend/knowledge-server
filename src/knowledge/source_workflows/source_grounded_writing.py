"""Prepare source-cited writing points and draft prose.

Generated text must cite validated information blocks and never accepts knowledge
records as a side effect.
"""

import json
import re
from collections.abc import Callable
from typing import Final

from pydantic import Field, JsonValue

from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.model_integration import structured_generation
from knowledge.source_workflows import information_block_extraction

MAX_WRITING_CHARACTERS: Final[int] = 120000
BLOCK_CITATION: Final[re.Pattern[str]] = re.compile(r"\[block:(\d+)\]")


class WritingPoint(models.Contract):
    """Pair one proposed writing point with its original information-block citations."""

    text: str = Field(min_length=1)
    block_indexes: list[int] = Field(min_length=1)


class WritingPoints(models.Contract):
    """Pin a writing goal and cited points for a later prose proposal."""

    goal: str = Field(min_length=1)
    points: list[WritingPoint] = Field(min_length=1, max_length=100)


class WritingDraft(models.Contract):
    """Keep proposed prose separate from source checks and a human's tone evaluation."""

    text: str = Field(min_length=1, max_length=30000)
    block_indexes: list[int] = Field(min_length=1)


def validate_block_citations(text: str, indexes: list[int], allowed: set[int]) -> None:
    """Require exact one-based block tokens and reject absent or invented references."""
    cited = {int(match) for match in BLOCK_CITATION.findall(text)}
    declared = set(indexes)
    if not cited or cited != declared or not declared <= allowed:
        raise ValueError("Text must cite exactly its declared, supplied [block:N] references")
    if len(indexes) != len(declared):
        raise ValueError("Block references must not repeat")


def validate_writing_points(
    points: WritingPoints,
    blocks: information_block_extraction.InformationBlocks,
    goal: str,
) -> None:
    """Preserve the requested goal and verify every point's original source references."""
    if points.goal != goal:
        raise ValueError("Writing output changed the requested goal")
    allowed = set(range(1, len(blocks.blocks) + 1))
    for point in points.points:
        validate_block_citations(point.text, point.block_indexes, allowed)


def prepare_writing_points(
    goal: str,
    extraction: information_block_extraction.TextExtraction,
    blocks: information_block_extraction.InformationBlocks,
    context: dict[str, JsonValue],
    instructions: str,
    configuration: structured_generation.ModelConfiguration,
    cancelled: Callable[[], bool],
) -> WritingPoints:
    """Compose points against original spans and explicit upstream proposal context."""
    if not goal.strip():
        raise ValueError("Set a writing goal before preparing cited points")
    information_block_extraction.validate_blocks(blocks, extraction)
    packet = bounded_writing_packet(
        {"goal": goal, "blocks": blocks.model_dump(mode="json"), "context": context}
    )
    return structured_generation.generate(
        instructions,
        packet,
        WritingPoints,
        lambda result: validate_writing_points(result, blocks, goal),
        configuration=configuration,
        cancelled=cancelled,
    )


def draft_prose(
    points: WritingPoints,
    extraction: information_block_extraction.TextExtraction,
    blocks: information_block_extraction.InformationBlocks,
    author_rules: dict[str, JsonValue],
    instructions: str,
    configuration: structured_generation.ModelConfiguration,
    cancelled: Callable[[], bool],
) -> WritingDraft:
    """Apply explicit private author rules while retaining inspectable original citations."""
    if not author_rules:
        raise ValueError("Save and select private author rules before drafting prose")
    information_block_extraction.validate_blocks(blocks, extraction)
    validate_writing_points(points, blocks, points.goal)
    allowed = {index for point in points.points for index in point.block_indexes}
    packet = bounded_writing_packet(
        {
            "points": points.model_dump(mode="json"),
            "blocks": blocks.model_dump(mode="json"),
            "author_rules": author_rules,
        }
    )
    return structured_generation.generate(
        instructions,
        packet,
        WritingDraft,
        lambda result: validate_block_citations(result.text, result.block_indexes, allowed),
        configuration=configuration,
        cancelled=cancelled,
    )


def bounded_writing_packet(content: dict[str, JsonValue]) -> str:
    """Reject oversized writing context rather than silently truncating source evidence."""
    packet = json.dumps(
        {
            "citation_format": "Use [block:N] inline, where N is the one-based blocks list index. "
            "Declare those N values in block_indexes. Every factual point requires a token.",
            **content,
        },
        ensure_ascii=False,
    )
    if len(packet) > MAX_WRITING_CHARACTERS:
        raise ValueError("Writing context exceeds the 120000-character budget")
    return packet
