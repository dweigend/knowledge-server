"""Load database and archive settings from the process environment.

Host-specific locations and credentials stay outside application code and are
resolved once when an interface starts.
"""

import os
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BATCH = os.environ.get("KNOWLEDGE_DEFAULT_BATCH", "default")


class Settings(BaseSettings):
    """Required server locations; credentials remain in the process environment."""

    model_config = SettingsConfigDict(env_prefix="KNOWLEDGE_", frozen=True)

    database_url: str
    archive_root: Annotated[Path, AfterValidator(Path.resolve)]
