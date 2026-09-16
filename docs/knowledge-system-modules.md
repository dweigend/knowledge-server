# Research modules and skill reuse

The [Hermes integration target](hermes-integration-target.md), requested on
2026-09-16, takes precedence for agent execution, task ownership and extension
packaging. Reuse native Hermes runs, tasks, schedules, plugins and skills;
Knowledge keeps its domain operations and deterministic processing. This is a
target decision, not a claim of installed or deployed integration.

The [modular architecture](knowledge-plugin-architecture.md) defines the latest
approved two-entry workflow, public boundaries, dependency direction and
replacement criteria. Its diagrams and optional extension inventory are the
primary guide for future module separation. The earlier proposals below are
background; they do not require a generic kernel or a service per capability.

For the next source-view delivery, the
[binding specification](knowledge-source-view.md) takes precedence. Use the
existing application with Zotero, document extraction, knowledge operations and
web presentation as concrete responsibilities. The broader module proposals
below do not authorize new services, generic kernels, ports or retrieval layers
for this delivery. Remove superseded paths rather than wrapping them in another
architecture layer; preserve only explicitly required historical readers.

Updated: 2026-09-15. Status: target module boundaries and inspected reuse
assessment. The [application](README.md) implements the
first slice; broader integrations below remain proposals.
This supplements the [knowledge concept](knowledge-management-concept.md).
The [approved MVP](knowledge-mvp.md) adds claim assessments within Evidence and
Review; [local pilot contracts and rating rules](knowledge-contracts.md) are
implemented. The future Hub contract remains separate. The September 15
[approved workflow](knowledge-mvp.md#1-first-useful-outcome) prioritizes improving
existing entries and sole Zotero ownership of literature and PDFs. It supersedes
older proposals below where they imply a separate catalog or PDF store.

The implemented slice uses `literature/zotero_client.py` for the literature
boundary, `source_workflows/source_import.py` for staged ingestion,
`source_workflows/claim_reconciliation.py` for contribution decisions,
`source_workflows/passage_grounding.py` for passage attribution and
`source_workflows/note_consolidation.py` for existing-note revisions. They
reuse the knowledge base and revision store. No additional service, vector
database or retrieval abstraction was introduced. See the
[verification limits](README.md#historical-evidence-limits).

## 1. Three different architectural concepts

- **Harness:** Hermes runs the model/tool loop, sessions, context, interaction
  and recurring research skills on the Linux server.
- **Skill:** an instruction/procedure used by that harness. It selects module
  operations and interprets results; it does not own database rules or tables.
- **Module:** deterministic domain behavior with typed operations, validation
  and explicitly owned persistence. Modules do not run model loops.

A single Hermes harness can compose many modules without merging them. Start
with a modular application and reusable commands, not a service per module.
Separate deployment is justified when a component needs independent operation;
the podcast system explicitly has that requirement and its own scope.

## 2. Research module ownership

The following module names and operations are proposals, not implemented APIs.

### Shared kernel

Keep the shared contract vocabulary small; do not create a universal framework.
Own stable ID types, common contract envelopes, authenticated scope context,
revision conventions, checkpoint ledger and the unit-of-work interface.
Persist shared request/idempotency metadata and revision attribution through
small infrastructure services. Do not place source normalization, scientific
judgment, note logic, rendering or media production here.

### Sources and bibliography

Own source identities, source versions, Zotero library/item mapping and
controlled citation-key mapping. Resolve current metadata through Zotero; retain
historical citation text without a second editable catalog. Normalize provider
identifiers and distinguish editions/versions. A Zotero Web API adapter is an
external boundary; Zotero remains the literature authority.

Proposed operations: register source, import source version, resolve identity,
synchronize approved catalog scope, export citation mapping.
Outputs: source/version IDs, normalized metadata, mappings and sync provenance.
No evidence acceptance, note editing or research synthesis.

### Document extraction

The [approved extraction workflow](knowledge-extraction.md) defines this
responsibility as an independent module within the existing application,
with acceptance incomplete. Docling reads the complete document; Marker
visually re-reads table, scan and suspect pages. Deterministic checks expose
discrepancies before downstream knowledge operations use the content.

Own extraction jobs, one versioned document snapshot, page/block locations and
extraction QA. Reuse source identities and revision storage. Zotero alone owns
PDFs and literature metadata; processing files are temporary. Markdown and HTML
are derived views, not separate document stores. The existing import workflow
coordinates extraction with knowledge operations without taking over these
rules.

Public responsibilities are requesting extraction and reading status/results.
No scientific assessment, note mutation or model planning belongs here. One
Python worker and the existing PostgreSQL database are sufficient. Additional
adapters for web snapshots, chats or archived X records remain deferred.

### Evidence

Own claim propositions, exact evidence spans, claim/evidence relations, source
profiles and structural citation checks. Reuse Open Research Lab models and
locators. Semantic judgments arrive as explicit proposals produced by Hermes;
the module validates their representation and provenance.

Proposed operations: propose evidence span, propose claim, link claim/evidence,
validate source/locator structure. Outputs are revisioned evidence records and
validation results. Only Review records substantive acceptance.

### Notes and conceptual relations

Own Pandoc-Markdown note bodies, note kinds, structure notes, wiki revisions
and typed conceptual links with rationale. Notes reference immutable evidence
and source revisions through IDs; they do not copy editable bibliography or
evidence state into their own tables.

Proposed operations: capture note, propose/edit note, propose conceptual link,
resolve note revision. No collector, scholarly search or speech production.

### Review

Own attributed review decisions, the revision/dependency set assessed, review
policy and current eligibility for publication. Keep execution authorization,
structural validation and scientific acceptance distinct. A changed dependency
does not inherit an earlier acceptance.

For the approved MVP, also own overall claim assessments: evidence balance,
confidence with rationale, corpus coverage and the assessed dependency set.
Evidence owns individual evidence-relation appraisals; review status never
implies that a claim is true.

Proposed operations: record decision, assess publication eligibility, invalidate
affected current approval through a recorded change. Reviewed entities remain
owned by their modules; Review references their revision IDs.

### Retrieval

Own rebuildable text/search projections and retrieval configuration. Read scoped
source, passage, note and evidence views; return revision IDs, locators, scores
and coverage. PostgreSQL full-text search is the initial backend. Embeddings
are an optional later adapter with CPU/resource/privacy acceptance.

Proposed operations: search corpus, retrieve passage packet, traverse typed
links, rebuild projection. No writes to notes, claims or review decisions.

### Research text publication and export

Own research document revisions, paragraph-to-evidence links, bibliography
snapshots, publication manifests and text-export artifacts. Consume accepted
inputs through Review's eligibility contract. Use a citation-aware Pandoc/LaTeX
adapter for HTML, Markdown and research PDF outputs.

Proposed operations: propose research document, validate document references,
release accepted document, export checkpoint, export released content package.
No narration preparation, voice choice, speech rendering or podcast jobs.

### Interface and provider adapters

Translate web/Matrix/Codex request formats and provider responses into module
contracts. Authenticate before constructing the scope context. X/feed/provider
collectors emit versioned raw inputs; they do not own claims or acceptance.
Research notification adapters report research run/release state only.

Provider health and rates, file/database adapters and Linux process execution
are infrastructure concerns. Backup and restore are deterministic operational
jobs; an LLM is not responsible for their correctness or scheduling decisions.

## 3. Contracts, dependencies and writes

The common input/request/result envelopes are only the shared framing. Each
module specifies its own operation version, payload schema, preconditions,
output shape, error codes, permission requirements and revision expectations.
Do not introduce an untyped generic command that can mutate arbitrary tables.

Example operation distinctions:

- Extraction returns a source-version ID, passage locators, extraction version
  and QA results; it cannot return an accepted claim as a side effect.
- Evidence proposes a claim with revision-pinned spans; Review separately
  assesses those revisions and records a decision.
- Notes edits require an expected note revision; a citation mapping change
  goes through Sources, never through a note editor's raw database write.
- Publication returns an immutable released-text manifest; a media result is
  not a valid research-publication result payload.

Dependency rules:

1. Domain behavior depends on stable contracts and ports, not on UI, Hermes
   internals, PostgreSQL drivers or provider SDKs.
2. Modules use another module's public operation/read contract, not its tables
   or concrete repository. Adapters implement ports at the outer boundary.
3. Sources/ingestion provide versioned inputs; Evidence/Notes reference them;
   Review evaluates pinned revisions; Publication consumes eligible records.
   Retrieval reads scoped projections and never becomes a write path.
4. A deterministic application command coordinates multi-module transactions
   using the shared unit of work. Each participating module performs its own
   writes; there is no second model planner in this coordinator.
5. Source updates and affected review state are committed consistently. Avoid
   circular domain imports by exchanging stable IDs and change contracts.
6. Enforce module ownership in code and verification. A single initial database
   role is not a claimed security barrier between modules; SQL-role separation
   is an additional deployment decision.
7. The independent podcast system has no domain import or database-write access
   into Research. Shared envelope conventions do not imply shared job tables.

One PostgreSQL deployment may contain these research modules' tables and the
common revision ledger. Hermes state, existing research-project SQLite and
external Zotero remain separate authorities for their specified scope. The
reviewed-package integration decision is retained from the main concept.

## 4. Inspected skill reuse

The available skill catalog, relevant instruction files and selected helper
code were inspected. This is a compatibility assessment, not proof that a
skill is installed in Hermes or operational on the Linux server. No collection
bootstrap, external paid API call, Zotero mutation or extraction was executed.

### Scientific workflow skills

The existing `open-research-lab` skill family provides these reusable
procedures:

- `route-research`, `frame-research-field`: scoped questions, reviewed research
  landscapes, lanes and stopping rules. Adapt orchestration to Hermes while
  keeping deterministic query compilation and human gates.
- `search-literature`, `review-literature`, `map-literature-network`: recorded
  provider queries, normalization, screening, citation expansion and literature
  roles. Discovery rank is not evidence acceptance.
- `analyze-evidence`: bounded passage selection, exact spans, claims, source
  profiles and structural/semantic citation checks. Map persistence to Evidence
  and Review; acceptance remains explicit.
- `write-research-report`: structured synthesis from accepted evidence,
  paragraph links, revisioned drafts and verified exports. Map to research
  text publication; it supplies no podcast-generation workflow.
- `scan-horizons`: signals, baselines, counterevidence and uncertainty. Compose
  source, evidence and publication operations for recurring research briefs.
- `research-art-design`: specialized source/object locators through existing
  contracts; enable only for a relevant research lane.
- `research-qualitatively`: special local-processing/privacy rules. Sensitive
  recordings and transcripts must not be routed to the hosted model merely
  because Hermes is configured. Keep this extension disabled until an approved
  CPU-compatible private-processing path exists.
- `manage-research-project`, `inspect-research-provider`: explicit operations
  and diagnostics, distinct from ordinary research execution.

Reusable code locations in the `open-research-lab` repository, below
`plugins/open-research-lab/src/open_research_lab/`:

- `domain/models.py`: sources, versions, evidence, claims and review states.
- `domain/locators.py`: exact typed source positions.
- `domain/workflow.py`: separate citation validity and semantic audits.
- `application/envelope.py`: schema/run/result/provenance conventions.
- `ports/storage.py`: repositories, unit of work and binary-store ports.
- `adapters/storage/repositories.py`: current entity upserts; no universal
  revision history. Migration/publication capture is still required.

These procedures are complementary skills over module operations. Their
packaging does not justify a new agent framework or one module per skill.

### Other relevant skills

- `x-research`: useful signal/evidence separation, primary-source tracing and
  durable briefs. Helpers contain fixed project/storage paths and a coupled
  sync bootstrap. Adapt configuration and collector contracts; do not copy
  those paths or treat refresh as an implicit side effect of every search.
- `Zotero`: useful library/item/citation-key distinctions and controlled writes.
  The adapter uses Zotero Desktop
  through its local API. Future remote adapters must preserve instance,
  attachment and version checks; a changed base URL is not sufficient.
- `jazz-pdf-extractor`: source-faithful extraction, page mapping, chapter QA and
  uncertainty rules. Its music schema and MIDI outputs are specialized; reuse
  methods rather than imposing them on general books or importing music jobs.
- `latex-compile`, `latex-doctor`: toolchain detection and compile diagnostics.
  Retain only Linux-compatible paths/runtime detection for research text
  publication; installation and CPU smoke tests are separate acceptance work.
- `python-uv`: maintainable Python commands, typed validation, uv/Ruff/ty and
  transport/domain separation. These are development conventions, not another
  research runtime or a requirement to scaffold application code now.

Other available development, graphics and administrative skills are not
dependencies of this research architecture. No inspected research skill
justifies including a speech runtime or audio lifecycle in Research.

## 5. Linux and modularity acceptance

- Required tools run under Linux on CPU with observed peak RAM, elapsed time
  and bounded batch sizes. Hosted model inference is an explicit provider
  call, not a requirement for a local GPU/model service.
- Bibliographic lookup, text extraction, scoped retrieval and released-text
  export succeed without optional embeddings or any media service.
- Skill prompts cannot bypass module validation, set their own permissions or
  promote a proposal to accepted scientific content.
- A module-level contract change is tested against its consumers; transport
  changes do not change the evidence or citation meaning.
- Cross-module changes remain atomic and revision-safe; unauthorized table
  mutation paths are rejected or absent from the public command surface.
- Research startup, health, review and publication work with the podcast
  system removed. Media outages do not set research runs to failed.

Independent agent review and the resolved findings are recorded in the
[architecture review](knowledge-architecture-review.md).
