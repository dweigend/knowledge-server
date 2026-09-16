"""Define grounded query proposals and their typed source evidence."""

from typing import Annotated, Final

from pydantic import BaseModel, Field, TypeAdapter

from knowledge.knowledge_domain.knowledge_record_models import Contract
from knowledge.literature.literature_models import Candidate
from knowledge.literature.structured_paper_models import PaperReference

MAX_QUERY_REFERENCES: Final[int] = 50
MAX_QUERY_CANDIDATES: Final[int] = 6


class ReferenceQuery(Contract):
    """Select source-supported search fields without granting a confirmed identity."""

    reference_id: str
    title: str = Field(min_length=3, max_length=500)
    authors: list[str] = Field(default_factory=list, max_length=10)
    year: str | None = None
    reason: str = Field(max_length=1000)


class ReferenceQueries(Contract):
    """Return a bounded set of evidence-grounded alternative searches."""

    queries: list[ReferenceQuery] = Field(default_factory=list, max_length=MAX_QUERY_REFERENCES)


class CachedQueryPlan(BaseModel):
    """Keep a failed planning attempt from triggering repeated model requests."""

    plan: ReferenceQueries = Field(default_factory=ReferenceQueries)
    error: str | None = None


class ReferenceQueryEvidence(BaseModel):
    """Pair exact extracted reference evidence with bounded provider candidates."""

    reference: PaperReference
    candidates: list[Candidate] = Field(max_length=MAX_QUERY_CANDIDATES)


QUERY_EVIDENCE: Final[TypeAdapter[list[ReferenceQueryEvidence]]] = TypeAdapter(
    Annotated[list[ReferenceQueryEvidence], Field(max_length=MAX_QUERY_REFERENCES)]
)
