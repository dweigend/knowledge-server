"""Manage immutable document snapshots and extraction jobs.

Queue transitions and snapshot writes stay tied to source revisions while
heavyweight extraction runs outside database transactions.
"""

import hashlib
import json
from typing import Final

from psycopg.types.json import Jsonb

from knowledge.document_processing import document_models
from knowledge.document_processing.extraction_input_models import ExtractionJob, SnapshotRevision
from knowledge.knowledge_domain import (
    application_errors as errors,
)
from knowledge.knowledge_domain import (
    knowledge_record_models as models,
)
from knowledge.revision_store import postgresql_revision_store as store

CONFIGURATION: Final[str] = "docling-2.127.0-marker-2.0.0-raster-200dpi-v1"
MAX_ATTEMPTS: Final[int] = 2


def get_snapshot(
    ledger: store.Ledger, source: models.Reference, revision: int | None = None
) -> document_models.DocumentSnapshot | None:
    """Read a pinned extraction revision or the newest snapshot for this source version."""
    row = ledger.connection.execute(
        "SELECT payload FROM document_snapshots WHERE source_id=%s AND source_revision=%s "
        "AND (%s::integer IS NULL OR revision=%s) ORDER BY revision DESC LIMIT 1",
        (source.entity_id, source.revision, revision, revision),
    ).fetchone()
    return document_models.DocumentSnapshot.model_validate(row["payload"]) if row else None


def request_extraction(
    ledger: store.Ledger, source: models.Reference, retry_failed: bool = False
) -> str:
    """Queue an existing source version once for the pinned tool configuration."""
    record = ledger.get(source.entity_id, source.revision)
    if not isinstance(record.payload, models.Source):
        raise ValueError("Extraction requires a source")
    identity = [source.model_dump(mode="json"), record.payload.sha256, CONFIGURATION]
    request_hash = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    ledger.connection.execute(
        "INSERT INTO extraction_jobs(request_hash,source_id,source_revision,configuration) "
        "VALUES (%s,%s,%s,%s) ON CONFLICT (request_hash) DO NOTHING",
        (request_hash, source.entity_id, source.revision, CONFIGURATION),
    )
    if retry_failed:
        ledger.connection.execute(
            "UPDATE extraction_jobs SET state='queued',attempts=0,error='',updated_at=now() "
            "WHERE request_hash=%s AND state='failed'",
            (request_hash,),
        )
    return request_hash


def claim_job(ledger: store.Ledger) -> ExtractionJob | None:
    """Claim one queued job during a short serialized transaction."""
    row = ledger.connection.execute(
        "UPDATE extraction_jobs SET state='running', attempts=attempts+1, updated_at=now() "
        "WHERE request_hash=(SELECT request_hash FROM extraction_jobs "
        "WHERE state='queued' ORDER BY updated_at,request_hash LIMIT 1) RETURNING *"
    ).fetchone()
    return ExtractionJob.model_validate(row) if row is not None else None


def recover_jobs(ledger: store.Ledger) -> None:
    """Recover interrupted work after the worker has obtained its singleton lock."""
    ledger.connection.execute(
        "UPDATE extraction_jobs SET state=CASE WHEN attempts < %s THEN 'queued' "
        "ELSE 'failed' END, error='Worker interrupted', updated_at=now() WHERE state='running'",
        (MAX_ATTEMPTS,),
    )


def fail_job(ledger: store.Ledger, request_hash: str, error: str, transient: bool) -> None:
    """Retry a transient failure once and retain persistent errors for inspection."""
    ledger.connection.execute(
        "UPDATE extraction_jobs SET state=CASE WHEN %s AND attempts < %s THEN 'queued' "
        "ELSE 'failed' END, error=%s, updated_at=now() WHERE request_hash=%s AND state='running'",
        (transient, MAX_ATTEMPTS, error, request_hash),
    )


def save_snapshot(
    ledger: store.Ledger, request_hash: str, snapshot: document_models.DocumentSnapshot
) -> None:
    """Append the checked snapshot and finish its job in the same transaction."""
    validate_snapshot_job(ledger, request_hash, snapshot)
    append_snapshot(ledger, request_hash, snapshot)
    ledger.connection.execute(
        "UPDATE extraction_jobs SET state='succeeded', error='', updated_at=now() "
        "WHERE request_hash=%s",
        (request_hash,),
    )


def append_snapshot(
    ledger: store.Ledger, request_hash: str, snapshot: document_models.DocumentSnapshot
) -> None:
    """Append an already validated result without changing existing extraction revisions."""
    previous = get_snapshot(ledger, snapshot.source)
    snapshot.revision = previous.revision + 1 if previous else 1
    ledger.connection.execute(
        "INSERT INTO document_snapshots(source_id,source_revision,revision,request_hash,payload) "
        "VALUES (%s,%s,%s,%s,%s)",
        (
            snapshot.source.entity_id,
            snapshot.source.revision,
            snapshot.revision,
            request_hash,
            Jsonb(snapshot.model_dump(mode="json")),
        ),
    )


def validate_snapshot_job(
    ledger: store.Ledger, request_hash: str, snapshot: document_models.DocumentSnapshot
) -> None:
    """Require the active job, source identity and PDF provenance to agree."""
    row = ledger.connection.execute(
        "SELECT * FROM extraction_jobs WHERE request_hash=%s",
        (request_hash,),
    ).fetchone()
    job = ExtractionJob.model_validate(row) if row is not None else None
    expected = (snapshot.source.entity_id, snapshot.source.revision, snapshot.method, "running")
    actual = (job.source_id, job.source_revision, job.configuration, job.state) if job else None
    if actual != expected:
        raise ValueError("Snapshot does not match its running extraction job")
    source = ledger.get(snapshot.source.entity_id, snapshot.source.revision).payload
    if not isinstance(source, models.Source) or source.sha256 != snapshot.pdf_sha256:
        raise ValueError("Extraction PDF does not match the pinned source")
    if source.zotero != snapshot.zotero or snapshot.zotero.original_sha256 != source.sha256:
        raise ValueError("Extraction Zotero reference does not match the pinned source")


def annotate_document(ledger: store.Ledger, annotation: document_models.DocumentAnnotation) -> int:
    """Persist explicit source inspection as a new snapshot without changing extracted wording."""
    identity = hashlib.sha256(annotation.model_dump_json().encode()).hexdigest()
    previous = ledger.connection.execute(
        "SELECT revision FROM document_snapshots WHERE request_hash=%s",
        (identity,),
    ).fetchone()
    if previous:
        return SnapshotRevision.model_validate(previous).revision
    snapshot = get_snapshot(ledger, annotation.source)
    if snapshot is None:
        raise errors.Missing("No extraction to annotate")
    if snapshot.revision != annotation.expected_revision:
        raise errors.Conflict("Extraction changed before annotation")
    apply_annotations(snapshot, annotation)
    append_snapshot(ledger, identity, snapshot)
    return snapshot.revision


def apply_annotations(
    snapshot: document_models.DocumentSnapshot,
    annotation: document_models.DocumentAnnotation,
) -> None:
    """Check that classification and relationships refer to exact located source content."""
    blocks = {block.id: block for block in snapshot.blocks}
    if not (annotation.block_kinds.keys() | annotation.block_issues.keys()) <= blocks.keys():
        raise ValueError("Annotation names an unknown source block")
    for relationship in annotation.relationships:
        origin, target = blocks.get(relationship.from_id), blocks.get(relationship.to_id)
        if origin is None or target is None or origin.page is None or target.page is None:
            raise ValueError("Relationship requires located source blocks")
        if not relationship.origin_text or relationship.origin_text not in origin.text:
            raise ValueError("Relationship origin must be exact source text")
        if not relationship.target_text or relationship.target_text not in target.text:
            raise ValueError("Relationship target must be exact source text")
    for block_id, kind in annotation.block_kinds.items():
        blocks[block_id].kind = kind
    for block_id, issues in annotation.block_issues.items():
        blocks[block_id].issues = list(dict.fromkeys([*blocks[block_id].issues, *issues]))
    snapshot.relationships = annotation.relationships
    snapshot.annotation = f"{annotation.actor}: {annotation.reason}"
