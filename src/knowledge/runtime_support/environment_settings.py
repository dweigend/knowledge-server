"""Load database and archive settings from the process environment.

Host-specific locations and credentials stay outside application code and are
resolved once when an interface starts.
"""

import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BATCH = os.environ.get("KNOWLEDGE_DEFAULT_BATCH", "default")


class Settings(BaseSettings):
    """Required server locations; credentials remain in the process environment."""

    model_config = SettingsConfigDict(env_prefix="KNOWLEDGE_", extra="ignore", frozen=True)

    database_url: str
    archive_root: Path

    @field_validator("archive_root", mode="after")
    @classmethod
    def resolve_archive_root(cls, archive_root: Path) -> Path:
        """Resolve the archive path once at startup."""
        return archive_root.expanduser().resolve()
