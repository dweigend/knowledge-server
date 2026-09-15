"""Server configuration; no credentials are embedded in application code."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Self

DEFAULT_BATCH = os.environ.get("KNOWLEDGE_DEFAULT_BATCH", "default")


@dataclass(frozen=True)
class Settings:
    """Required server locations; credentials remain in the process environment."""

    database_url: str
    archive_root: Path

    @classmethod
    def from_environment(cls) -> Self:
        """Load required settings and resolve the archive path once at startup."""
        return cls(
            database_url=os.environ["KNOWLEDGE_DATABASE_URL"],
            archive_root=Path(os.environ["KNOWLEDGE_ARCHIVE_ROOT"]).resolve(),
        )
