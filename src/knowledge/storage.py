"""PostgreSQL revision ledger and atomic request receipts, internal to the application."""

import hashlib
import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from knowledge.contracts import (
    PAYLOAD_TYPES,
    Contract,
    Kind,
    LegacySource,
    Record,
    Reference,
    Source,
)


class Conflict(ValueError):
    """An idempotency identity or expected revision no longer matches."""


class Missing(ValueError):
    """The requested record does not exist."""


class Ledger:
    """Read and append revisioned records inside an existing transaction."""

    def __init__(self, connection: psycopg.Connection[dict]):
        """Use the active transaction connection for reads and writes."""
        self.connection = connection

    def get(self, entity_id: UUID, revision: int | None = None) -> Record:
        """Read an exact revision, or the latest when no revision is supplied."""
        row = self.connection.execute(
            "SELECT * FROM revisions WHERE entity_id = %s "
            "AND (%s::integer IS NULL OR revision = %s) ORDER BY revision DESC LIMIT 1",
            (entity_id, revision, revision),
        ).fetchone()
        if row is None:
            raise Missing(str(entity_id))
        row["created_at"] = row["created_at"].isoformat()
        row["payload"] = decode_payload(row["kind"], row["payload"])
        return Record.model_validate(row)

    def list(self, batch_id: str, kind: Kind | None = None, query: str = "") -> list[Record]:
        """Read current records in stable order with optional kind and text filters."""
        rows = self.connection.execute(
            "SELECT entity_id FROM current_records WHERE batch_id = %s "
            "AND (%s::text IS NULL OR kind = %s) "
            "AND (%s = '' OR to_tsvector('simple', payload::text) "
            "@@ plainto_tsquery('simple', %s)) ORDER BY kind, created_at, entity_id",
            (batch_id, kind, kind, query, query),
        ).fetchall()
        return [self.get(row["entity_id"]) for row in rows]

    def get_receipt(self, request_id: str) -> dict | None:
        """Return a completed command receipt, or None if it has not been accepted."""
        return self.connection.execute(
            "SELECT * FROM requests WHERE request_id = %s", (request_id,)
        ).fetchone()

    def save_receipt(
        self,
        request_id: str,
        batch_id: str,
        payload_hash: str,
        references: Sequence[Reference],
    ) -> None:
        """Record accepted references in the same transaction as the command writes."""
        self.connection.execute(
            "INSERT INTO requests(request_id, batch_id, payload_hash, result) "
            "VALUES (%s, %s, %s, %s)",
            (
                request_id,
                batch_id,
                payload_hash,
                Jsonb([ref.model_dump(mode="json") for ref in references]),
            ),
        )

    def append(
        self,
        batch_id: str,
        kind: Kind,
        payload: Contract,
        actor: str,
        expected: Reference | None = None,
    ) -> Reference:
        """Append a new record or revision after checking concurrent edits."""
        entity_id = uuid4() if expected is None else expected.entity_id
        revision = self.next_revision(batch_id, kind, expected)
        self.connection.execute(
            "INSERT INTO revisions(entity_id, revision, batch_id, kind, actor, payload) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (entity_id, revision, batch_id, kind, actor, Jsonb(payload.model_dump(mode="json"))),
        )
        return Reference(entity_id=entity_id, revision=revision)

    def next_revision(self, batch_id: str, kind: Kind, expected: Reference | None) -> int:
        """Choose the next revision only if the expected record still matches."""
        if expected is None:
            return 1
        current = self.get(expected.entity_id)
        if current.revision != expected.revision:
            raise Conflict("Stale revision")
        if current.kind != kind or current.batch_id != batch_id:
            raise Conflict("Record ownership mismatch")
        return current.revision + 1

    def require(self, reference: Reference, batch_id: str, kind: Kind | None = None) -> Record:
        """Resolve a pinned reference and enforce batch and record-kind ownership."""
        record = self.get(reference.entity_id, reference.revision)
        if record.batch_id != batch_id or (kind and record.kind != kind):
            raise ValueError("Reference is outside this batch or has the wrong kind")
        return record


class Database:
    """Own transaction boundaries and idempotent command acceptance."""

    def __init__(self, database_url: str):
        """Retain the supplied connection configuration without opening a transaction."""
        self.database_url = database_url

    @contextmanager
    def transaction(self) -> Iterator[Ledger]:
        """Serialize short database operations and roll back when an error escapes."""
        with psycopg.Connection[dict].connect(
            self.database_url, row_factory=dict_row
        ) as connection:
            # Pilot writes are short and serialized; model/file work happens before entry.
            connection.execute("SELECT pg_advisory_xact_lock(81420914)")
            yield Ledger(connection)

    def initialize(self) -> None:
        """Create the revision schema using the bundled SQL definition."""
        with self.transaction() as ledger:
            ledger.connection.execute(Path(__file__).with_name("schema.sql").read_bytes())

    def command(
        self,
        request_id: str,
        batch_id: str,
        operation: str,
        payload: Contract,
        actor: str,
        execute: Callable[[Ledger], list[Reference]],
    ) -> list[Reference]:
        """Commit domain writes and their receipt together, or reuse an identical request."""
        encoded = json.dumps(
            [operation, batch_id, actor, payload.model_dump(mode="json")],
            sort_keys=True,
        ).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        with self.transaction() as ledger:
            previous = ledger.get_receipt(request_id)
            if previous:
                return receipt_references(previous, digest)
            references = execute(ledger)
            ledger.save_receipt(request_id, batch_id, digest, references)
            return references


def receipt_references(receipt: dict, payload_hash: str) -> list[Reference]:
    """Decode an existing receipt only when its command payload matches."""
    if receipt["payload_hash"] != payload_hash:
        raise Conflict("Idempotency key reused with different content")
    return [Reference.model_validate(reference) for reference in receipt["result"]]


def decode_payload(kind: Kind, payload: dict) -> Contract:
    """Decode new sources and immutable legacy sources through their respective contracts."""
    if kind == "source":
        return TypeAdapter(Source | LegacySource).validate_python(payload)
    return PAYLOAD_TYPES[kind].model_validate(payload)
