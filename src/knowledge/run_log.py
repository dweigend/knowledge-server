"""Append inspectable workflow events without a separate logging service."""

import json
from datetime import UTC, datetime
from pathlib import Path


def record_event(directory: Path, event: str, **details: object) -> None:
    """Append a timestamped decision or failure to the private run log."""
    directory.mkdir(parents=True, exist_ok=True)
    entry = {"time": datetime.now(UTC).isoformat(), "event": event, **details}
    with (directory / "events.jsonl").open("a") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(entry, ensure_ascii=False, default=str), flush=True)
