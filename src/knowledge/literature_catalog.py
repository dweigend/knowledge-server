"""Build a read-only literature network from current isolated extraction results."""

from pathlib import Path

from knowledge.experimentation import list_experiments, read_attempts
from knowledge.literature_contracts import LiteratureRecord


def literature_catalog(root: Path) -> list[dict]:
    """Group stable work identities while retaining each document's citation observations."""
    catalog: dict[str, dict] = {}
    for source in list_experiments(root):
        if source.get("legacy") or source.get("cleanup_pending"):
            continue
        attempts = [
            attempt
            for attempt in read_attempts(root, source["id"])
            if attempt["step"] == "extract_text" and attempt["status"] == "completed"
        ]
        if not attempts:
            continue
        attempt = attempts[-1]
        for payload in attempt["output"].get("literature", []):
            record = LiteratureRecord.model_validate(payload)
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
