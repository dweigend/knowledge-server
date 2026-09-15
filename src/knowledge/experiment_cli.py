"""Inspect and rerun private experiments through the dashboard's shared runner."""

import argparse
import json
import os
from pathlib import Path

from knowledge import experimentation as experiments
from knowledge.contracts import Record
from knowledge.pipeline_steps import STEP_LABELS
from knowledge.prompt_registry import resolve_recipe, seed_defaults


def create_parser() -> argparse.ArgumentParser:
    """Declare independent experiment commands without a production database connection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=Path(os.environ.get("KNOWLEDGE_ARCHIVE_ROOT", ".local/archive")),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Copy a PDF and optional pinned knowledge records")
    create.add_argument("pdf", type=Path)
    create.add_argument("--seed-json", type=Path, help="JSON list of complete immutable Records")
    run = commands.add_parser("run", help="Manually run one step with a saved recipe")
    run.add_argument("experiment")
    run.add_argument("step", choices=STEP_LABELS)
    run.add_argument("--recipe", help="Saved recipe name; defaults to the step name")
    run.add_argument(
        "--revision", type=int, help="Recipe revision; defaults to the active revision"
    )
    run.add_argument("--inputs", type=Path, help="JSON mapping of input step to attempt ID")
    inspect = commands.add_parser(
        "inspect", help="Read attempts, or list sources when no ID is given"
    )
    inspect.add_argument("experiment", nargs="?")
    export = commands.add_parser(
        "export", help="Export a private report, including inspected traces"
    )
    export.add_argument("experiment")
    export.add_argument("--output", type=Path, help="Create a new JSON file instead of printing")
    for name in ("cancel", "recover"):
        command = commands.add_parser(name, help=f"{name.capitalize()} a specified attempt")
        command.add_argument("experiment")
        command.add_argument("attempt")
    delete = commands.add_parser("delete", help="Delete one experiment, retaining saved recipes")
    delete.add_argument("experiment")
    return parser


def create_from_file(arguments: argparse.Namespace) -> dict:
    """Read explicit local inputs and delegate isolation to the shared experiment store."""
    if arguments.pdf.stat().st_size > experiments.MAX_PDF_BYTES:
        raise ValueError("Experiment PDFs must not exceed 64 MiB")
    records = []
    if arguments.seed_json:
        supplied = json.loads(arguments.seed_json.read_text())
        if not isinstance(supplied, list):
            raise ValueError("Seed JSON must be a list of complete immutable records")
        records = [Record.model_validate(record) for record in supplied]
    seed_defaults()
    identifier = experiments.create_experiment(
        arguments.archive_root, arguments.pdf.name, arguments.pdf.read_bytes(), records
    )
    return {"experiment_id": identifier}


def run_saved_step(arguments: argparse.Namespace) -> dict:
    """Pin and execute one step using exactly the runner invoked by the web interface."""
    seed_defaults()
    recipe, _, _, _ = resolve_recipe(arguments.recipe or arguments.step, arguments.revision)
    inputs = json.loads(arguments.inputs.read_text()) if arguments.inputs else None
    if inputs is not None and (
        not isinstance(inputs, dict)
        or any(
            not isinstance(step, str) or not isinstance(pin, str) for step, pin in inputs.items()
        )
    ):
        raise ValueError("Input JSON must map step names to immutable attempt IDs")
    identifier = experiments.prepare_attempt(
        arguments.archive_root, arguments.experiment, arguments.step, recipe, inputs
    )
    return experiments.execute_attempt(arguments.archive_root, arguments.experiment, identifier)


def dispatch(arguments: argparse.Namespace) -> dict | list[dict]:
    """Dispatch explicit commands while keeping reads free of configuration writes."""
    root = arguments.archive_root.expanduser()
    arguments.archive_root = root
    if arguments.command == "create":
        return create_from_file(arguments)
    if arguments.command == "run":
        return run_saved_step(arguments)
    if arguments.command == "inspect":
        if arguments.experiment:
            return {
                "manifest": experiments.read_manifest(root, arguments.experiment),
                "attempts": experiments.read_attempts(root, arguments.experiment),
            }
        return experiments.list_experiments(root)
    if arguments.command == "export":
        return experiments.export_experiment(root, arguments.experiment)
    if arguments.command == "cancel":
        experiments.request_cancel(root, arguments.experiment, arguments.attempt)
        return {"cancel_requested": arguments.attempt}
    if arguments.command == "recover":
        return experiments.recover_attempt(root, arguments.experiment, arguments.attempt)
    experiments.delete_experiment(root, arguments.experiment)
    return {"deleted": arguments.experiment, "saved_configuration_retained": True}


def main(argv: list[str] | None = None) -> int:
    """Print inspectable JSON and return failure status when an attempted step fails."""
    parser = create_parser()
    arguments = parser.parse_args(argv)
    try:
        result = dispatch(arguments)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        destination = getattr(arguments, "output", None)
        if destination is None:
            print(output)
        else:
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(output + "\n")
            print(json.dumps({"report": str(destination)}))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return int(
        arguments.command == "run"
        and isinstance(result, dict)
        and result.get("status") in {"failed", "cancelled"}
    )


if __name__ == "__main__":
    raise SystemExit(main())
