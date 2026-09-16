"""Validate database row envelopes before exposing domain records."""

from datetime import datetime

from pydantic import BaseModel

from knowledge.knowledge_domain import knowledge_record_models as models


class CommandReceipt(BaseModel):
    """Retain the accepted command identity and its immutable result references."""

    request_id: str
    batch_id: str
    payload_hash: str
    result: list[models.Reference]
    created_at: datetime
