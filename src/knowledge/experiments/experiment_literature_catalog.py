"""Build a read-only literature network from completed experiment results.

The projection combines resolved paper identities and citation occurrences
without mutating canonical knowledge or Zotero.
"""

from pathlib import Path
from typing import TypedDict

from pydantic import TypeAdapter

from knowledge.experiments.experiment_runner import list_experiments, read_attempts
from knowledge.literature import literature_models


class LiteratureDocument(TypedDict):
    """Link one observed literature record to its source experiment."""

    run_id: str
    filename: str
    attempt_id: str
    record: literature_models.LiteratureRecord


class LiteratureEntry(TypedDict):
    """Group a resolved work and the documents citing it."""

    record: literature_models.LiteratureRecord
    documents: list[LiteratureDocument]


def literature_catalog(root: Path) -> list[LiteratureEntry]:
    """Group stable work identities while retaining each document's citation observations."""
    catalog: dict[str, LiteratureEntry] = {}
    for source in list_experiments(root):
        attempts = [
            attempt
            for attempt in read_attempts(root, source["id"])
            if attempt["step"] == "extract_text" and attempt["status"] == "completed"
        ]
        if not attempts:
            continue
        attempt = attempts[-1]
        output = attempt["output"]
        if output is None:
            continue
        records = TypeAdapter(list[literature_models.LiteratureRecord]).validate_python(
            output.get("literature", [])
        )
        for record in records:
            entry = catalog.setdefault(record.id, {"record": record, "documents": []})
            if record.resolution.checked_at > entry["record"].resolution.checked_at:
                entry["record"] = record
            entry["documents"].append(
                {
                    "run_id": source["id"],
                    "filename": source["filename"],
                    "attempt_id": attempt["id"],
                    "record": record,
                }
            )
    return sorted(
        catalog.values(), key=lambda entry: (entry["record"].metadata.title or "").lower()
    )
