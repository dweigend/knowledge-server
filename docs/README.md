# Documentation guide

Knowledge Server is an experimental Python application, not a stable public
service. These documents preserve its design rationale and distinguish working
code from proposed extensions. Start with the [project README](../README.md)
for installation and the [coding rules](../AGENTS.md) for contributions.

## Implementation status

The application includes PostgreSQL revision history, pinned source references,
Zotero integration, claims and evidence, assessments, human review, note
consolidation, command-line operations and a plain HTML review interface.
These are implementation descriptions, not guarantees of scientific correctness
or production readiness.

Structured document extraction and the source article view are partially
implemented. Docling and Marker adapters, snapshot contracts, background jobs,
annotations and source rendering exist. End-to-end extraction acceptance and
corpus migration remain incomplete. Older ingestion paths still require review
before they can be treated as fully migrated structured-content consumers.

The following remain plans: a general inbox, independent plugin APIs, research
question schemas, citation-network and embedding indexes, evaluated authoring
rules, remote dashboard integration and released-text publication. Zotero note,
annotation and tag ownership also has pending migration work. A design diagram
or a passing unit test does not establish these capabilities as deployed.

The [self-hosted WebDAV decision](knowledge-webdav-sync.md) is a binding target
for personal-library file sync, iPad access and annotation intake. Provisioning,
client migration and end-to-end acceptance are pending.

## Reading order

- [MVP](knowledge-mvp.md): product scope and incremental priorities.
- [Contracts](knowledge-contracts.md): records, citation integrity and assessment
  rules; historical compatibility requirements remain explicit.
- [Self-hosted file sync](knowledge-webdav-sync.md): binding WebDAV target,
  mobile workflow, annotation intake and migration acceptance.
- [Zotero ownership](knowledge-zotero-ownership.md): literature responsibilities
  and outstanding migration requirements.
- [Extraction](knowledge-extraction.md): Docling/Marker workflow and module
  operations, with unresolved content and acceptance criteria.
- [Source view](knowledge-source-view.md): structured article presentation and
  citation-preserving replacement rules.
- [Module architecture](knowledge-plugin-architecture.md): proposed boundaries
  and two intake paths; not a completed plugin framework.
- [Structure and quality](knowledge-structure-and-quality.md): future schemas,
  contextual relevance and authoring evaluation.

## Historical design material

The [original concept](knowledge-management-concept.md) and
[module inventory](knowledge-system-modules.md) explain broader possibilities.
The narrower specifications above take precedence; these documents do not
require a service, abstraction or dependency for every proposed capability.
The [architecture review](knowledge-architecture-review.md) reviewed the design,
not runtime acceptance. The [podcast boundary](podcast-system-boundary.md)
describes a possible independent consumer; this project contains no podcast
service and does not require one.

## Historical evidence limits

The design was informed by private pilot documents and extraction experiments.
Those PDFs, personal records, host inventories, raw model outputs and deployment
reports are intentionally not published. Historical observations in these
specifications are design rationale, not independently reproducible benchmarks.

Public tests use synthetic fixtures. Before relying on extraction quality,
select an appropriately licensed representative corpus, pin tool versions and
configuration, and compare output against manually checked source passages,
tables and footnotes. Do not infer accuracy across a corpus from one successful
page, tool agreement or schema validation. Published quality claims require
shareable fixtures and reproducible results.

## Retained pilot records

- [Consolidation experiment](knowledge-consolidation-test.md): observed failures,
  limited synthesis results and the next useful evaluation.
- [Source-view implementation record](knowledge-source-view-implementation.md):
  reuse decisions and the still-incomplete extraction acceptance.

Machine-specific runbooks, intake artifacts and recovery material belong in the
ignored `.local/migrated-server-state/` directory on the original maintainer's
checkout. They are not required to install or contribute to this project and
are not distributed on GitHub. The former server setup repository retains only
one project pointer.
