"""Server commands; no model is needed for initialization, reads or exports."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from knowledge.application import Knowledge
from knowledge.backup import snapshot, verify_restore
from knowledge.comparison import enrich
from knowledge.config import DEFAULT_BATCH, Settings
from knowledge.consolidation import consolidate
from knowledge.contracts import Record
from knowledge.document_contracts import DocumentAnnotation
from knowledge.document_extraction import annotate_document, request_extraction
from knowledge.extraction_worker import run_pending
from knowledge.import_workflow import import_manifest
from knowledge.migration import migrate_sources
from knowledge.operations import MUTATIONS, run_operation
from knowledge.pilot import run_pilot
from knowledge.storage import Database


def create_parser() -> argparse.ArgumentParser:
    """Declare the pilot commands and their shared command-line options."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "init",
            "extract",
            "extract-worker",
            "annotate-document",
            "consolidate",
            "import",
            "migrate-zotero",
            "pilot",
            "compare",
            "export",
            "backup",
            "read",
            "search",
            "passage",
            "schema",
            *MUTATIONS,
        ],
    )
    parser.add_argument("--batch", default=DEFAULT_BATCH)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--entity")
    parser.add_argument("--revision", type=int)
    parser.add_argument("--page", type=int)
    parser.add_argument("--query", default="")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--operation", choices=list(MUTATIONS), default="propose-note")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--request-id")
    parser.add_argument("--retry-failed", action="store_true")
    return parser


def validate_arguments(parser: argparse.ArgumentParser, arguments: argparse.Namespace) -> None:
    """Reject missing output paths and unsupported pilot sizes before dispatch."""
    if arguments.command in {"consolidate", "import"} and arguments.output is None:
        parser.error("--output is required for the private run log")
    if arguments.command == "import" and arguments.input is None:
        parser.error("import requires --input manifest.json")
    if arguments.command == "pilot" and not 1 <= arguments.limit <= 10:
        parser.error("--limit must be 1..10")
    if arguments.command in {"backup", "export"} and arguments.output is None:
        parser.error(f"{arguments.command} requires --output")
    if arguments.command == "extract" and arguments.entity is None:
        parser.error("extract requires --entity")
    if arguments.command == "annotate-document" and arguments.input is None:
        parser.error("annotate-document requires --input")


def export_record(application: Knowledge, record: Record, output: Path) -> None:
    """Write one revision history and, for notes, its current Markdown."""
    history = application.history(record.entity_id)
    (output / f"{record.kind}-{record.entity_id}.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
    )
    if record.kind != "note":
        return
    payload = record.payload.model_dump()
    (output / f"note-{record.entity_id}.md").write_text(
        f"# {payload['title']}\n\n{payload['body']}\n",
    )


def export_batch(application: Knowledge, batch_id: str, output: Path) -> None:
    """Export revision histories and the current Markdown notes."""
    with application.database.transaction() as ledger:
        records = ledger.list(batch_id)
    output.mkdir(parents=True, exist_ok=True)
    for record in records:
        export_record(application, record, output)


def backup_and_report(application: Knowledge, settings: Settings, output: Path) -> None:
    """Hold the application write lock during the snapshot, then verify its restore."""
    with application.database.transaction():
        directory = snapshot(settings, output)
    report = {
        "snapshot": str(directory),
        "verification": verify_restore(directory, settings.database_url),
    }
    print(json.dumps(report))


def dispatch_command(
    application: Knowledge,
    settings: Settings,
    arguments: argparse.Namespace,
) -> None:
    """Separate workflow commands from storage operations and individual record commands."""
    if arguments.command in {"extract", "extract-worker", "annotate-document"}:
        run_document_command(application, settings, arguments)
        return
    if arguments.command in {"pilot", "import", "consolidate", "compare"}:
        run_workflow(application, settings, arguments)
        return
    if arguments.command in {"init", "migrate-zotero", "backup", "export"}:
        run_storage_command(application, settings, arguments)
        return
    run_operation(application, arguments)


def run_document_command(
    application: Knowledge,
    settings: Settings,
    arguments: argparse.Namespace,
) -> None:
    """Queue extraction, run pending work or save an explicit source inspection."""
    if arguments.command == "annotate-document":
        annotation = DocumentAnnotation.model_validate_json(arguments.input.read_text())
        with application.database.transaction() as ledger:
            print(annotate_document(ledger, annotation))
        return
    if arguments.command == "extract-worker":
        run_pending(settings)
        return
    if arguments.command == "extract":
        with application.database.transaction() as ledger:
            record = ledger.get(UUID(arguments.entity), arguments.revision)
            print(request_extraction(ledger, record.reference(), arguments.retry_failed))
        return


def run_workflow(application: Knowledge, settings: Settings, arguments: argparse.Namespace) -> None:
    """Run the selected import or evidence workflow through its existing entry point."""
    if arguments.command == "pilot":
        run_pilot(settings, arguments.batch, arguments.limit)
        return
    if arguments.command == "import":
        import_manifest(application, arguments.batch, arguments.input, arguments.output)
        return
    if arguments.command == "consolidate":
        consolidate(application, arguments.batch, arguments.output)
        return
    enrich(
        application,
        arguments.batch,
        settings.archive_root / arguments.batch,
        Path(__file__).with_name("prompts"),
    )


def run_storage_command(
    application: Knowledge, settings: Settings, arguments: argparse.Namespace
) -> None:
    """Run initialization, migration, backup or export without generating knowledge."""
    if arguments.command == "init":
        application.database.initialize()
        return
    if arguments.command == "migrate-zotero":
        print(json.dumps(migrate_sources(application.database, arguments.batch)))
        return
    if arguments.command == "backup":
        backup_and_report(application, settings, arguments.output)
        return
    export_batch(application, arguments.batch, arguments.output)


def main() -> None:
    """Load configuration, validate arguments and run the selected command."""
    parser = create_parser()
    arguments = parser.parse_args()
    settings = Settings.from_environment()
    application = Knowledge(Database(settings.database_url))
    validate_arguments(parser, arguments)
    dispatch_command(application, settings, arguments)


if __name__ == "__main__":
    main()
