from pathlib import Path

from knowledge import backup
from knowledge.config import Settings


def test_settings_use_configured_locations(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_DATABASE_URL", "dbname=example")
    monkeypatch.setenv("KNOWLEDGE_ARCHIVE_ROOT", str(tmp_path / "archive"))

    settings = Settings.from_environment()

    assert settings.database_url == "dbname=example"
    assert settings.archive_root == tmp_path / "archive"


def test_postgres_utilities_default_to_path(monkeypatch):
    calls = []
    monkeypatch.delenv("KNOWLEDGE_POSTGRES_BIN", raising=False)
    monkeypatch.setattr(backup.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    backup.run_postgres("pg_dump", "--version")

    assert calls == [(["pg_dump", "--version"],)]


def test_postgres_utilities_allow_explicit_installation(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("KNOWLEDGE_POSTGRES_BIN", str(tmp_path))
    monkeypatch.setattr(backup.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    backup.run_postgres("pg_dump", "--version")

    assert calls == [([str(tmp_path / "pg_dump"), "--version"],)]


def test_runtime_resources_are_inside_package():
    package = Path(backup.__file__).parent
    assert (package / "prompts/import.md").is_file()
    assert (package / "schema.sql").is_file()
    assert (package / "templates/index.html").is_file()
    assert (package / "static/pdfjs/build/pdf.worker.mjs").is_file()
