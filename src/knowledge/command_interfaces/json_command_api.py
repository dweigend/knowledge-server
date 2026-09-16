"""Expose a small deterministic JSON command surface.

The adapter translates structured reads and mutations for Hermes and other callers
without bypassing application validation.
"""

import argparse
import json
from pathlib import Path
from uuid import UUID

from knowledge.document_processing import document_models, extraction_store
from knowledge.knowledge_base import knowledge_service, review_records
from knowledge.knowledge_domain import knowledge_record_models as models

MUTATIONS = {
    "propose-note": models.Note,
    "edit-note": knowledge_service.EditNote,
    "link-evidence": models.Evidence,
    "assess": knowledge_service.AssessmentCommand,
}
SEARCH_PAGE_SIZE = 20
TOOL_ACTOR = "hermes:knowledge-tool"


def search_records(application: knowledge_service.Knowledge, arguments: argparse.Namespace) -> dict:
    """Return one search page with review status and total count."""
    with application.database.transaction() as ledger:
        records = ledger.list(arguments.batch, query=arguments.query)
        page = records[arguments.offset : arguments.offset + SEARCH_PAGE_SIZE]
        summaries = [
            {
                "reference": record.reference().model_dump(mode="json"),
                "kind": record.kind,
                "status": review_records.status(ledger, record),
                "summary": record.payload.model_dump(exclude={"pages"}),
            }
            for record in page
        ]
    return {"total": len(records), "offset": arguments.offset, "records": summaries}


def read_passage(
    record: models.Record,
    page: int | None,
    snapshot: document_models.DocumentSnapshot | None = None,
) -> dict:
    """Return a validated page from a stored source snapshot."""
    source = record.payload
    if not isinstance(source, models.Source) or not page:
        raise ValueError("passage requires a source and --page")
    if snapshot is not None:
        return structured_passage(snapshot, page)
    if not 1 <= page <= len(source.pages):
        raise ValueError("Page is outside the source")
    return {
        "source": record.reference().model_dump(mode="json"),
        "page": page,
        "text": source.pages[page - 1],
    }


def structured_passage(snapshot: document_models.DocumentSnapshot, page: int) -> dict:
    """Return located blocks with the pins and restrictions needed for new evidence."""
    if page not in snapshot.page_sizes:
        raise ValueError("Page is outside the extracted document")
    return {
        "source": snapshot.source.model_dump(mode="json"),
        "page": page,
        "extraction_revision": snapshot.revision,
        "blocks": [
            block.model_dump(mode="json") for block in snapshot.blocks if block.page == page
        ],
        "evidence_rule": "Quote a single-page prose block without issues; include block_id "
        "and extraction_revision. Tables and furniture cannot automatically supply evidence.",
    }


def read_record(application: knowledge_service.Knowledge, arguments: argparse.Namespace) -> dict:
    """Read a record or source page with its pinned dependencies."""
    if not arguments.entity:
        raise ValueError("--entity is required")
    with application.database.transaction() as ledger:
        record = ledger.get(UUID(arguments.entity), arguments.revision)
        if arguments.command == "passage":
            snapshot = extraction_store.get_snapshot(ledger, record.reference())
            return read_passage(record, arguments.page, snapshot)
        return {
            "record": record.model_dump(mode="json"),
            "status": review_records.status(ledger, record),
            "dependencies": [
                reference.model_dump(mode="json")
                for reference in review_records.dependencies(ledger, record)
            ],
        }


def apply_mutation(
    application: knowledge_service.Knowledge, arguments: argparse.Namespace
) -> list[models.Reference]:
    """Validate CLI input and submit the corresponding application command."""
    if not arguments.input or not arguments.request_id:
        raise ValueError("Mutations require --input and a stable --request-id")
    payload = MUTATIONS[arguments.command].model_validate_json(Path(arguments.input).read_text())
    if isinstance(payload, models.Note):
        return application.propose_note(arguments.request_id, arguments.batch, payload, TOOL_ACTOR)
    if isinstance(payload, knowledge_service.EditNote):
        return application.edit_note(arguments.request_id, arguments.batch, payload, TOOL_ACTOR)
    if isinstance(payload, models.Evidence):
        return application.link_evidence(arguments.request_id, arguments.batch, payload, TOOL_ACTOR)
    assert isinstance(payload, knowledge_service.AssessmentCommand)
    return application.assess(arguments.request_id, arguments.batch, payload, TOOL_ACTOR)


def run_operation(application: knowledge_service.Knowledge, arguments: argparse.Namespace) -> None:
    """Dispatch a deterministic operation and print its JSON response."""
    if arguments.command == "schema":
        print(json.dumps(MUTATIONS[arguments.operation].model_json_schema(), indent=2))
        return
    if arguments.command == "search":
        print(json.dumps(search_records(application, arguments), ensure_ascii=False, default=str))
        return
    if arguments.command in {"read", "passage"}:
        print(json.dumps(read_record(application, arguments), ensure_ascii=False))
        return
    references = apply_mutation(application, arguments)
    print(json.dumps([reference.model_dump(mode="json") for reference in references]))
