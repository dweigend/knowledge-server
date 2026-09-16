"""Write durable JSON documents without exposing partial file contents.

The helper publishes a fully flushed temporary file with one atomic replacement,
then flushes the containing directory so callers can rely on durable visibility.
"""

import json
import os
import tempfile
from pathlib import Path

from pydantic import JsonValue


def write_json_atomically(path: Path, content: dict[str, JsonValue]) -> None:
    """Publish a complete private JSON file and flush its directory entry."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(content, output, ensure_ascii=False, sort_keys=True, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
