"""Small deterministic JSON command surface for Hermes and future adapters."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from knowledge import review
from knowledge.application import AssessmentCommand, EditNote, Knowledge
from knowledge.contracts import Evidence, Note, Record, Reference, Source
from knowledge.document_contracts import DocumentSnapshot
from knowledge.document_extraction import get_snapshot

MUTATIONS = {
    "propose-note": Note,
    "edit-note": EditNote,
    "link-evidence": Evidence,
    "assess": AssessmentCommand,
}
SEARCH_PAGE_SIZE = 20
TOOL_ACTOR = "hermes:knowledge-tool"


def search_records(application: Knowledge, arguments: argparse.Namespace) -> dict:
    """Return one search page with review status and total count."""
    with application.database.transaction() as ledger:
        records = ledger.list(arguments.batch, query=arguments.query)
        page = records[arguments.offset : arguments.offset + SEARCH_PAGE_SIZE]
        summaries = [
            {
                "reference": record.reference().model_dump(mode="json"),
                "kind": record.kind,
                "status": review.status(ledger, record),
                "summary": record.payload.model_dump(exclude={"pages"}),
            }
            for record in page
        ]
    return {"total": len(records), "offset": arguments.offset, "records": summaries}


def read_passage(
    record: Record, page: int | None, snapshot: DocumentSnapshot | None = None
) -> dict:
    """Return a validated page from a stored source snapshot."""
    source = record.payload
    if not isinstance(source, Source) or not page:
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


def structured_passage(snapshot: DocumentSnapshot, page: int) -> dict:
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


def read_record(application: Knowledge, arguments: argparse.Namespace) -> dict:
    """Read a record or source page with its pinned dependencies."""
    if not arguments.entity:
        raise ValueError("--entity is required")
    with application.database.transaction() as ledger:
        record = ledger.get(UUID(arguments.entity), arguments.revision)
        if arguments.command == "passage":
            snapshot = get_snapshot(ledger, record.reference())
            return read_passage(record, arguments.page, snapshot)
        return {
            "record": record.model_dump(mode="json"),
            "status": review.status(ledger, record),
            "dependencies": [
                reference.model_dump(mode="json")
                for reference in review.dependencies(ledger, record)
            ],
        }


def apply_mutation(application: Knowledge, arguments: argparse.Namespace) -> list[Reference]:
    """Validate CLI input and submit the corresponding application command."""
    if not arguments.input or not arguments.request_id:
        raise ValueError("Mutations require --input and a stable --request-id")
    payload = MUTATIONS[arguments.command].model_validate_json(Path(arguments.input).read_text())
    if isinstance(payload, Note):
        return application.propose_note(arguments.request_id, arguments.batch, payload, TOOL_ACTOR)
    if isinstance(payload, EditNote):
        return application.edit_note(arguments.request_id, arguments.batch, payload, TOOL_ACTOR)
    if isinstance(payload, Evidence):
        return application.link_evidence(arguments.request_id, arguments.batch, payload, TOOL_ACTOR)
    assert isinstance(payload, AssessmentCommand)
    return application.assess(arguments.request_id, arguments.batch, payload, TOOL_ACTOR)


def run_operation(application: Knowledge, arguments: argparse.Namespace) -> None:
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
