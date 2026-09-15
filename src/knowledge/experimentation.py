"""Run disposable, manually advanced experiments through shared operations."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from knowledge.information_blocks import TextExtraction, extract_text, segment_verbatim
from knowledge.run_log import record_event

ExperimentStep = Literal[
    "extract_text",
    "segment_blocks",
    "formulate_claims",
    "find_knowledge",
    "select_entries",
    "propose_changes",
    "prepare_writing",
    "draft_text",
]

STEP_LABELS: dict[ExperimentStep, str] = {
    "extract_text": "Extract PDF text",
    "segment_blocks": "Segment information blocks",
    "formulate_claims": "Formulate general claims",
    "find_knowledge": "Find existing knowledge",
    "select_entries": "Select relevant entries",
    "propose_changes": "Propose grounded changes",
    "prepare_writing": "Prepare cited writing points",
    "draft_text": "Draft text in David's voice",
}


def experiments_root(archive_root: Path) -> Path:
    """Resolve the disposable experiment directory beside the archive."""
    return archive_root.parent / "experiments"


def create_experiment(archive_root: Path, filename: str, content: bytes) -> str:
    """Create an isolated experiment and retain only its private source copy."""
    if not filename.lower().endswith(".pdf"):
        raise ValueError("Experiment sources must be PDF files")
    if not content:
        raise ValueError("Experiment source is empty")
    experiment_id = uuid4().hex
    directory = experiments_root(archive_root) / experiment_id
    directory.mkdir(parents=True, mode=0o700)
    (directory / "source.pdf").write_bytes(content)
    manifest = {
        "id": experiment_id,
        "filename": Path(filename).name,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "created",
        "steps": {},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
    record_event(directory, "experiment_created", filename=Path(filename).name)
    return experiment_id


def experiment_directory(archive_root: Path, experiment_id: str) -> Path:
    """Resolve one experiment without allowing path traversal."""
    if not experiment_id.isalnum() or len(experiment_id) != 32:
        raise ValueError("Invalid experiment id")
    root = experiments_root(archive_root).resolve()
    directory = (root / experiment_id).resolve()
    if directory.parent != root or not directory.is_dir():
        raise FileNotFoundError("Experiment does not exist")
    return directory


def read_manifest(archive_root: Path, experiment_id: str) -> dict:
    """Read an experiment manifest without running any model operation."""
    path = experiment_directory(archive_root, experiment_id) / "manifest.json"
    return json.loads(path.read_text())


def run_step(
    archive_root: Path,
    experiment_id: str,
    step: ExperimentStep,
    *,
    max_characters: int = 2000,
) -> dict:
    """Run exactly one manually requested step and persist its inspectable output."""
    directory = experiment_directory(archive_root, experiment_id)
    manifest = read_manifest(archive_root, experiment_id)
    if step == "extract_text":
        result = extract_text(directory / "source.pdf")
        output = result.model_dump(mode="json")
        (directory / "extraction.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))
    elif step == "segment_blocks":
        extraction = TextExtraction.model_validate_json((directory / "extraction.json").read_text())
        result = segment_verbatim(extraction, max_characters=max_characters)
        output = result.model_dump(mode="json")
        (directory / "blocks.json").write_text(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        output = {
            "status": "unavailable",
            "reason": "This shared operation is not wired into the experiment runner yet.",
        }
    status = "completed" if output.get("status") != "unavailable" else "unavailable"
    manifest["steps"][step] = {"status": status}
    manifest["status"] = "active"
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    record_event(directory, "step_finished", step=step, output=output)
    return output


def delete_experiment(archive_root: Path, experiment_id: str) -> None:
    """Delete only one disposable experiment directory and report cleanup failures."""
    shutil.rmtree(experiment_directory(archive_root, experiment_id))
