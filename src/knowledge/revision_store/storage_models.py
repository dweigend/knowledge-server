"""Validate database row envelopes before exposing domain records."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from knowledge.knowledge_domain import knowledge_record_models as models


class RevisionRow(BaseModel):
    """Decode PostgreSQL metadata and retain the payload for kind-specific validation."""

    entity_id: UUID
    revision: int
    batch_id: str
    kind: models.Kind
    actor: str
    created_at: datetime
    payload: dict[str, object]


class EntityRow(BaseModel):
    """Identify a current entity returned by a database query."""

    entity_id: UUID


class CommandReceipt(BaseModel):
    """Retain the accepted command identity and its immutable result references."""

    request_id: str
    batch_id: str
    payload_hash: str
    result: list[models.Reference]
    created_at: datetime
