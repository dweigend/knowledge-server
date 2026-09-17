"""Append inspectable events for workflows and tool execution.

The lightweight JSONL log records structured progress without introducing a
separate logging service or changing canonical knowledge.
"""

import json
from datetime import UTC, datetime
from pathlib import Path


def record_event(directory: Path, event: str, **details: object) -> None:
    """Append a timestamped decision or failure to the private run log."""
    directory.mkdir(parents=True, exist_ok=True)
    entry = {"time": datetime.now(UTC).isoformat(), "event": event, **details}
    encoded = json.dumps(entry, ensure_ascii=False, default=str)
    with (directory / "events.jsonl").open("a") as stream:
        stream.write(encoded + "\n")
    print(encoded, flush=True)
