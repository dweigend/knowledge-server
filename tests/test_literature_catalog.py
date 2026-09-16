from pathlib import Path

import pytest

from knowledge.experiments.experiment_literature_catalog import literature_catalog
from knowledge.literature.literature_models import LiteratureMetadata, LiteratureRecord, Resolution


def test_catalog_groups_confirmed_work_identity_across_current_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = LiteratureRecord(
        id="doi:10.1234/shared",
        role="reference",
        source_sha256="a" * 64,
        metadata=LiteratureMetadata(title="Shared source"),
        resolution=Resolution(status="matched", checked_at="2026-09-15", message="Fixture"),
    )
    sources = [{"id": "first", "filename": "first.pdf"}, {"id": "second", "filename": "second.pdf"}]
    monkeypatch.setattr(
        "knowledge.experiments.experiment_literature_catalog.list_experiments", lambda root: sources
    )

    def attempts(root: Path, source_id: str) -> list[dict[str, object]]:
        return [
            {
                "step": "extract_text",
                "status": "completed",
                "id": "old",
                "output": {"literature": []},
            },
            {
                "step": "extract_text",
                "status": "completed",
                "id": "current",
                "output": {"literature": [record.model_dump()]},
            },
            {"step": "extract_text", "status": "failed", "id": "failed", "output": None},
        ]

    monkeypatch.setattr(
        "knowledge.experiments.experiment_literature_catalog.read_attempts", attempts
    )
    catalog = literature_catalog(tmp_path)
    assert len(catalog) == 1
    assert [document["run_id"] for document in catalog[0]["documents"]] == ["first", "second"]
    assert all(document["attempt_id"] == "current" for document in catalog[0]["documents"])
    sources.pop()
    assert len(literature_catalog(tmp_path)[0]["documents"]) == 1
