"""Expose operational knowledge commands through the command line.

Argument parsing and dispatch translate user input into application, workflow,
extraction, backup, migration, and deterministic record operations.
"""

import argparse
import json
from pathlib import Path
from uuid import UUID

from knowledge.command_interfaces import json_command_api
from knowledge.document_processing import document_models, extraction_store
from knowledge.knowledge_base import knowledge_service
from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.revision_store import postgresql_revision_store
from knowledge.runtime_support import environment_settings
from knowledge.source_workflows import (
    document_extraction_worker,
    note_consolidation,
    source_import,
)
from knowledge.system_maintenance import backup_and_restore, zotero_source_migration


def create_parser() -> argparse.ArgumentParser:
    """Declare knowledge commands and their shared command-line options."""
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
            "export",
            "backup",
            "read",
            "search",
            "passage",
            "schema",
            *json_command_api.MUTATIONS,
        ],
    )
    parser.add_argument("--batch", default=environment_settings.DEFAULT_BATCH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--entity")
    parser.add_argument("--revision", type=int)
    parser.add_argument("--page", type=int)
    parser.add_argument("--query", default="")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--operation", choices=list(json_command_api.MUTATIONS), default="propose-note"
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--request-id")
    parser.add_argument("--retry-failed", action="store_true")
    return parser


def validate_arguments(parser: argparse.ArgumentParser, arguments: argparse.Namespace) -> None:
    """Reject missing paths required by the selected command."""
    if arguments.command in {"consolidate", "import"} and arguments.output is None:
        parser.error("--output is required for the private run log")
    if arguments.command == "import" and arguments.input is None:
        parser.error("import requires --input manifest.json")
    if arguments.command in {"backup", "export"} and arguments.output is None:
        parser.error(f"{arguments.command} requires --output")
    if arguments.command == "extract" and arguments.entity is None:
        parser.error("extract requires --entity")
    if arguments.command == "annotate-document" and arguments.input is None:
        parser.error("annotate-document requires --input")


def export_record(
    application: knowledge_service.Knowledge, record: models.Record, output: Path
) -> None:
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


def export_batch(application: knowledge_service.Knowledge, batch_id: str, output: Path) -> None:
    """Export revision histories and the current Markdown notes."""
    with application.database.transaction() as ledger:
        records = ledger.list(batch_id)
    output.mkdir(parents=True, exist_ok=True)
    for record in records:
        export_record(application, record, output)


def backup_and_report(
    application: knowledge_service.Knowledge,
    settings: environment_settings.Settings,
    output: Path,
) -> None:
    """Hold the application write lock during the snapshot, then verify its restore."""
    with application.database.transaction():
        directory = backup_and_restore.snapshot(settings, output)
    report = {
        "snapshot": str(directory),
        "verification": backup_and_restore.verify_restore(directory, settings.database_url),
    }
    print(json.dumps(report))


def dispatch_command(
    application: knowledge_service.Knowledge,
    settings: environment_settings.Settings,
    arguments: argparse.Namespace,
) -> None:
    """Separate workflow commands from storage operations and individual record commands."""
    if arguments.command in {"extract", "extract-worker", "annotate-document"}:
        run_document_command(application, settings, arguments)
        return
    if arguments.command in {"import", "consolidate"}:
        run_workflow(application, arguments)
        return
    if arguments.command in {"init", "migrate-zotero", "backup", "export"}:
        run_storage_command(application, settings, arguments)
        return
    json_command_api.run_operation(application, arguments)


def run_document_command(
    application: knowledge_service.Knowledge,
    settings: environment_settings.Settings,
    arguments: argparse.Namespace,
) -> None:
    """Queue extraction, run pending work or save an explicit source inspection."""
    if arguments.command == "annotate-document":
        annotation = document_models.DocumentAnnotation.model_validate_json(
            arguments.input.read_text()
        )
        with application.database.transaction() as ledger:
            print(extraction_store.annotate_document(ledger, annotation))
        return
    if arguments.command == "extract-worker":
        document_extraction_worker.run_pending(settings)
        return
    if arguments.command == "extract":
        with application.database.transaction() as ledger:
            record = ledger.get(UUID(arguments.entity), arguments.revision)
            print(
                extraction_store.request_extraction(
                    ledger, record.reference(), arguments.retry_failed
                )
            )
        return


def run_workflow(
    application: knowledge_service.Knowledge,
    arguments: argparse.Namespace,
) -> None:
    """Run the selected source workflow through its existing entry point."""
    if arguments.command == "import":
        source_import.import_manifest(
            application, arguments.batch, arguments.input, arguments.output
        )
        return
    if arguments.command == "consolidate":
        note_consolidation.consolidate(application, arguments.batch, arguments.output)


def run_storage_command(
    application: knowledge_service.Knowledge,
    settings: environment_settings.Settings,
    arguments: argparse.Namespace,
) -> None:
    """Run initialization, migration, backup or export without generating knowledge."""
    if arguments.command == "init":
        application.database.initialize()
        return
    if arguments.command == "migrate-zotero":
        print(
            json.dumps(
                zotero_source_migration.migrate_sources(application.database, arguments.batch)
            )
        )
        return
    if arguments.command == "backup":
        backup_and_report(application, settings, arguments.output)
        return
    export_batch(application, arguments.batch, arguments.output)


def main() -> None:
    """Load configuration, validate arguments and run the selected command."""
    parser = create_parser()
    arguments = parser.parse_args()
    settings = environment_settings.Settings.from_environment()
    application = knowledge_service.Knowledge(
        postgresql_revision_store.Database(settings.database_url)
    )
    validate_arguments(parser, arguments)
    dispatch_command(application, settings, arguments)


if __name__ == "__main__":
    main()
