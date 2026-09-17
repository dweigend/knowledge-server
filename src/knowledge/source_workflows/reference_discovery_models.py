"""Keep reference discovery evidence and resolution state together."""

from pydantic import BaseModel, Field

from knowledge.literature import literature_models
from knowledge.literature import reference_discovery_models as models
from knowledge.literature import structured_paper_models as papers
from knowledge.source_workflows.bibliography_recovery_models import BibliographyAudit


class ReferenceDiscoveryResult(BaseModel):
    """Return recovered source evidence, literature records and the bounded search audit."""

    paper: papers.PaperDocument
    literature: list[literature_models.LiteratureRecord]
    report: models.DiscoveryReport
    bibliography: BibliographyAudit


class ReferenceSearchState(BaseModel):
    """Keep one source's original evidence, search identity and resolution together."""

    original: papers.PaperReference
    reference: papers.PaperReference
    record: literature_models.LiteratureRecord
    trace: models.ReferenceSearch
    candidates: list[literature_models.Candidate] = Field(default_factory=list)
