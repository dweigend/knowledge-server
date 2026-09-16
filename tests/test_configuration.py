from pathlib import Path

import pytest
from pydantic import ValidationError

import knowledge.model_integration.prompt_registry as prompt_registry
import knowledge.revision_store.postgresql_revision_store as database
import knowledge.system_maintenance.backup_and_restore as backup
import knowledge.web_interface.fastapi_app as web
from knowledge.runtime_support.environment_settings import Settings


def test_settings_use_configured_locations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_DATABASE_URL", "dbname=example")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KNOWLEDGE_ARCHIVE_ROOT", "archive")

    settings = Settings()

    assert settings.database_url == "dbname=example"
    assert settings.archive_root == tmp_path / "archive"
    monkeypatch.delenv("KNOWLEDGE_DATABASE_URL")
    with pytest.raises(ValidationError, match="database_url"):
        Settings()


def test_postgres_utilities_default_to_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.delenv("KNOWLEDGE_POSTGRES_BIN", raising=False)
    monkeypatch.setattr(backup.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    backup.run_postgres("pg_dump", "--version")

    assert calls == [(["pg_dump", "--version"],)]


def test_postgres_utilities_allow_explicit_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    monkeypatch.setenv("KNOWLEDGE_POSTGRES_BIN", str(tmp_path))
    monkeypatch.setattr(backup.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    backup.run_postgres("pg_dump", "--version")

    assert calls == [([str(tmp_path / "pg_dump"), "--version"],)]


def test_runtime_resources_are_inside_package() -> None:
    modeling_package = Path(prompt_registry.__file__).parent
    ledger_package = Path(database.__file__).parent
    presentation_package = Path(web.__file__).parent

    assert (modeling_package / "prompts/import.md").is_file()
    assert (ledger_package / "schema.sql").is_file()
    assert (presentation_package / "templates/index.html").is_file()
    assert (presentation_package / "static/pdfjs/build/pdf.worker.mjs").is_file()
