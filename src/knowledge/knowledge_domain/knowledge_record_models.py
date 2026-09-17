"""Define the revisioned records shared by the knowledge domain.

These Pydantic contracts describe stable references, sources, claims, evidence,
assessments, notes, reviews, and stored record envelopes.
"""

from datetime import datetime
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)

Text = Annotated[str, Field(min_length=1, max_length=30000)]
Kind = Literal["source", "claim", "evidence", "assessment", "note", "review"]
Relation = Literal["supports", "contradicts", "qualifies", "unclear"]
Balance = Literal["open", "mostly_supported", "mixed", "mostly_contradicted"]
Confidence = Literal["low", "medium", "high"]


class Contract(BaseModel):
    """Reject unknown fields and trim surrounding whitespace in text inputs."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Reference(Contract):
    """Pin an entity to one immutable revision."""

    entity_id: UUID
    revision: int = Field(ge=1)


class Bibliography(Contract):
    """Hold supplied-version metadata and the linked Zotero library item identity."""

    title: Text
    authors: list[str]
    year: str
    doi: str
    url: str
    zotero_key: str = ""
    zotero_library: str = ""
    zotero_version: int = 0


class ZoteroReference(Contract):
    """Pin literature and PDF versions to one Zotero instance and library."""

    server_id: Text
    library: str = "users/0"
    item_key: Text
    original_attachment_key: Text
    original_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    clean_attachment_key: Text
    clean_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Source(Contract):
    """Keep a citation text snapshot; Zotero owns metadata and PDF attachments.

    sha256 identifies the original PDF. pages preserves the extraction's page
    numbering, including any legacy excluded-cover placeholder.
    """

    zotero: ZoteroReference
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pages: list[str] = Field(min_length=1)
    extraction_method: Text
    extraction_warnings: list[str]
    study_group: Text
    overlap: Text


class LegacySource(Source):
    """Decode immutable pre-migration revisions without making them writable literature."""

    zotero: ZoteroReference | None = None
    bibliography: Bibliography
    original_path: Text
    archive_path: Text


class Claim(Contract):
    """State a proposition together with its scope and qualifications."""

    proposition: Text
    scope: Text
    qualifications: Text


class Evidence(Contract):
    """Link a claim revision to a verbatim quote on a one-based original PDF page."""

    claim: Reference
    source: Reference
    page: int = Field(ge=1)
    quote: Text
    relation: Relation
    rationale: Text
    directness: Literal["direct", "indirect", "unclear"]
    methodology: Text
    limitations: Text
    extraction_revision: int | None = Field(default=None, ge=1, exclude_if=lambda pin: pin is None)
    block_id: str | None = Field(default=None, min_length=1, exclude_if=lambda pin: pin is None)

    @model_validator(mode="after")
    def validate_extraction_pin(self) -> Self:
        """Require a document revision and block identifier together."""
        if (self.extraction_revision is None) != (self.block_id is None):
            raise ValueError("Evidence requires both extraction_revision and block_id")
        return self


class Assessment(Contract):
    """Summarize the complete evidence set for one claim revision.

    balance describes support versus counterevidence; confidence describes how
    well the available evidence warrants that assessment, not a truth probability.
    """

    claim: Reference
    evidence: list[Reference]
    balance: Balance
    confidence: Confidence
    rationale: Text
    coverage: Text
    limitations: Text


class Note(Contract):
    """Store source summaries, permanent notes or wiki prose with pinned references."""

    kind: Literal["inbox", "source", "permanent", "wiki"]
    title: Text
    body: Text
    references: list[Reference] = Field(min_length=1)


class Review(Contract):
    """Record a human verdict against a target and its dependency revisions."""

    target: Reference
    dependencies: list[Reference]
    verdict: Literal["reviewed", "revise", "rejected"]
    comment: Text


class Record(Contract):
    """Wrap an immutable domain payload with identity, authorship and revision metadata."""

    entity_id: UUID
    revision: int
    batch_id: str
    kind: Kind
    actor: str
    created_at: str
    payload: Source | LegacySource | Claim | Evidence | Assessment | Note | Review

    @field_validator("created_at", mode="before")
    @classmethod
    def normalize_creation_time(cls, timestamp: object) -> object:
        """Preserve the serialized timestamp when reading PostgreSQL rows."""
        return timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp

    @field_validator("payload", mode="before")
    @classmethod
    def decode_payload(cls, payload: object, info: ValidationInfo) -> object:
        """Select the record contract from its stored kind, including legacy sources."""
        kind = info.data.get("kind")
        if kind == "source":
            return _SOURCE_PAYLOAD.validate_python(payload)
        if kind in PAYLOAD_TYPES:
            return PAYLOAD_TYPES[kind].model_validate(payload)
        return payload

    def reference(self) -> Reference:
        """Return a citation pinned to this exact record revision."""
        return Reference(entity_id=self.entity_id, revision=self.revision)


class ExtractedClaim(Contract):
    """Carry a proposed claim and its source passage before assigning stored references."""

    proposition: Text
    scope: Text
    qualifications: Text
    page: int = Field(ge=1)
    quote: Text
    relation: Relation
    rationale: Text
    directness: Literal["direct", "indirect", "unclear"]
    methodology: Text
    limitations: Text


PAYLOAD_TYPES: Final[dict[Kind, type[Contract]]] = {
    "source": Source,
    "claim": Claim,
    "evidence": Evidence,
    "assessment": Assessment,
    "note": Note,
    "review": Review,
}

_SOURCE_PAYLOAD: Final[TypeAdapter[Source | LegacySource]] = TypeAdapter(Source | LegacySource)
