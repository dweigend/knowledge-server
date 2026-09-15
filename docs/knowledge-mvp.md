# Knowledge MVP and claim assessment

The [structured knowledge and authoring plan](knowledge-structure-and-quality.md)
adds the next approved quality slice: relevance to the author's research, typed
database metadata and relations, general claims with precise study evidence,
and tested author rules for reusable Zettel. Markdown is prose/export, not the
relationship schema. These requirements and the graph/embedding plan remain
pending implementation; they do not change the pilot results recorded below.

The [binding source-view specification](knowledge-source-view.md) adds the next
approved delivery: an article overview with citations, affiliations, sections,
figures, tables and references. Acceptance remains incomplete. Its minimal
architecture and replacement rules supersede conflicting earlier proposals.

The [document extraction module](knowledge-extraction.md) is the approved next
processing step: Docling for document structure, Marker for visual second
readings and explicit checks before knowledge ingestion. Its background worker
and structured snapshots are implemented in part. It shares the source-view
contract and keeps Zotero as the sole literature and PDF authority.

Decision dates: 2026-09-14 and 2026-09-15. Status: approved product direction.
The September 15 revision below supersedes automatic per-source note creation
and a separate PDF archive. The code includes this workflow; private pilot
results are not distributed as reproducible public acceptance evidence.
The initial decision below is preserved. A server pilot, local contracts and
rating rules are implemented; see the [status index](README.md) and
[contracts](knowledge-contracts.md). The pilot includes selected PDFs, Zotero
import and an unstyled HTML review interface.
This narrows the first delivery of the
[target architecture](knowledge-management-concept.md) and follows the existing
[module boundaries](knowledge-system-modules.md).

## 1. First useful outcome

Improve a compact body of source-linked knowledge as new sources arrive.
A source should first make existing claims, Zettel and wiki articles more
precise,
clearer, better supported and less repetitive. Better does not mean longer.
Create a new entry only for an independent contribution; impose no fixed cap on
entries that would suppress a genuinely new idea.

The approved [modular workflow](knowledge-plugin-architecture.md) has two
entry paths: an independent link/PDF inbox and an existing Zotero source.
The inbox is temporary intake, not a literature catalog. Its automatic worker
and independently replaceable plugin boundaries are target requirements;
the implementation status remains separate from these target requirements.

```text
Inbox link/PDF OR existing Zotero source → identify and extract
→ find existing candidates → propose improvement, link, new entry or no change
→ validate → verify Zotero ownership → accept knowledge → complete intake
```

Zotero ownership must be confirmed before canonical knowledge acceptance.
These two writes are resumable steps, not one cross-system transaction.
See the modular specification for diagrams, contracts and extension boundaries.

One source need not produce a Zettel or a wiki article. An uncertain match goes
to review rather than becoming an automatic merge or duplicate. Personal
thoughts
remain valid notes without pretending to be scientific evidence.

### Reconciliation rules

- Compare population, conditions, outcome and time period explicitly.
- Match only an identifier supplied in the candidate packet. Similarity is not
  proof of equivalence, contradiction or truth.
- Add evidence to an existing claim when its meaning and scope match. Preserve
  meaning when improving wording; a material meaning change requires a new
claim.
- Revise Zettel and wiki articles selectively. Remove repetition and expose
  qualifications or counterevidence instead of appending every new summary.
- Update assessments when their evidence changes. Evidence may grow while the
  visible knowledge collection remains compact.
- Deduplicate identical evidence using the pinned claim, source text version,
  passage and relation. Do not conflate different relations or independent
studies.
- Keep stable IDs, revisions and historical citations. For human-edited text,
  present a proposed change with a short rationale and diff before applying it.
- Defer merging existing entries with redirects from their old IDs. That is a
  later capability, not a prerequisite for avoiding new duplicates.

### Candidate retrieval

Use PostgreSQL full-text search and explicit references as the starting point.
Combine these with vector candidates in the same PostgreSQL database when an
embedding provider and model have been selected and verified. Merge results by
record ID and send a small candidate list to Luna. No separate vector database
or ranking framework is needed; pgvector is a possible implementation choice.

Prioritize claims including their scope and source passages including context.
Find existing notes through text and references first; embed notes only when
that improves observed retrieval. An embedding is a rebuildable index identified
by text-version reference, content hash and model identifier. It does not own a
second copy of the source text and does not decide the reconciliation action.

### Sources and technical snapshots

Zotero is the sole literature and PDF authority. Resolve current metadata and
PDFs through its adapter. Retain cited PDF versions as Zotero attachments and
keep one immutable extracted text snapshot in the knowledge database for exact
citation validation. Record attachment identity, content hash and page mapping.
A changed or missing PDF must never silently replace the file behind an old
quote.

Use temporary processing files only as staging. Existing historical backups are
recovery artifacts, not an editable catalog. Transfer and verify the existing
original PDFs before deleting any application-owned copies. Do not treat the
incoming source folder as disposable merely because pilot copies were migrated.

### Observed implementation and remaining work

Imports reconcile contributions before creating claims and do not require note
creation. Consolidation revises existing notes with stable identities. Private
logs retain decisions, rejected proposals and text diffs for review.

The historical pilot informed these workflows but its private corpus and
results are not published. Vector retrieval remains deferred until an observed
retrieval failure justifies it. Software validation alone does not establish
useful synthesis or factual accuracy. Reproduce representative quality checks
before expanding autonomous ingestion or claiming broad reliability.

## 2. Architecture and scope

Build one modular Python application with readable names, explicit types and
small domain-focused operations. Apply KISS, YAGNI and Separation of Concerns.
Reuse existing code and dependencies before adding new ones. Do not introduce
another agent orchestrator or a service for each module.

- Hermes owns model interaction and workflow orchestration through narrow tools.
- PostgreSQL owns central knowledge records and complete revision history.
- Zotero owns bibliography and PDF versions; the database pins citation text.
- Notes share one model with inbox, source, permanent and structure/wiki kinds.
- Markdown exports are derived portable snapshots.
- Initial retrieval uses PostgreSQL full-text search and explicit links.

Keep business rules, persistence, configuration, interfaces and orchestration
separate. Manual operations and Hermes tools use the same application rules.
No application scaffold or additional dependency is required at this stage.

The foundation includes exact provenance, immutable revisions, atomic changes,
idempotent commands, conflict detection and review of pinned revisions. Backup
and an isolated restore check are separate from history and export.

Defer bulk import, automated literature discovery, a graph database and research
PDF publication. Vector retrieval follows the bounded plan above. The existing
plain HTML interface remains the review surface until the separate dashboard
task.
Do not introduce a competing literature catalog.

## 3. Claim and evidence register

An extracted assertion starts as a claim, not an established fact. Each claim
records its precise proposition and scope, such as population, conditions,
outcome and time period. A reviewed claim is not automatically true.

| Record | Responsibility |
| --- | --- |
| Claim | A precise assertion, scope and qualifications |
| Evidence span | An exact passage and locator in an immutable source version |
| Evidence relation | Supports, contradicts, qualifies or unclear |
| Relation appraisal | Reasoning, directness and methodological limitations |
| Overall assessment | Balance, confidence, rationale and review state |

A competing thesis is another claim; it only supplies counterevidence when
backed by relevant evidence. Start with claim-to-evidence relations. Defer a
general claim-to-claim argument graph.

Keep three questions separate: how sound is the underlying study or source,
how directly does it address this claim, and how strong is the combined evidence
basis? Peer review is context rather than an automatic quality guarantee.

## 4. Assessment dimensions

Use the following product labels. Precise thresholds, examples and transition
rules will be specified before implementation.

| Dimension | Initial labels |
| --- | --- |
| Evidence balance | Open / mostly supported / mixed / mostly contradicted |
| Confidence in assessment | Low / medium / high, with mandatory rationale |
| Review workflow | Proposed / reviewed / needs renewed review |

German display labels are `offen`, `überwiegend gestützt`, `gemischt`,
`überwiegend widersprochen`; `gering`, `mittel`, `hoch`; and `vorgeschlagen`,
`geprüft`, `erneute Prüfung nötig`. Stable API values remain a contract
decision.

Confidence concerns the robustness of the assessment, including an assessment
that contradicts a claim. It is not a percentage probability of truth.

Rules accepted for the MVP:

- Do not count supporting and opposing texts as votes for truth.
- Several publications reporting the same study are not independent evidence.
  Initially record study/dataset groupings manually and expose unknown overlap.
  Reviews may overlap with their included primary studies.
- Missing evidence and imprecise or inconclusive results are not automatically
  counterevidence. Record uncertainty and relevance explicitly.
- State the evaluated corpus and search coverage. An assessment of selected
  sources is not a claim of complete scientific consensus.
- New relevant evidence or changed dependencies require renewed review of the
  current assessment. Preserve the previous assessment and its pinned inputs.
- Retrieval and wiki synthesis expose relevant counterevidence and limitations.

Illustrative example: a claim about four-week retention receives direct support
from a four-week study. A study measuring immediate performance has limited
directness. A blog repeating the four-week study adds no independent basis.
An imprecise result remains unclear. The assessment might be mostly supported
with low confidence; its rationale must explain why.

These are project-specific dimensions, informed by the distinction between
individual-study appraisal and certainty across a body of evidence in the
[Cochrane Handbook, chapter 14](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-14),
and study/report handling in
[chapter 5](https://training.cochrane.org/handbook/current/chapter-05).
This is not an implementation of the full GRADE framework or a universal rubric.

## 5. Ownership within existing modules

| Module | MVP ownership |
| --- | --- |
| Sources / ingestion | Source identities, versions, passages and locators |
| Evidence | Claims, evidence relations and individual appraisal proposals |
| Review | Overall assessments, decisions and their pinned dependencies |
| Notes | Zettel and wiki prose referencing claims and evidence |
| Retrieval | Relevant records, counterevidence and coverage information |
| Export | Derived Markdown snapshots |

The register extends Evidence and Review; it does not require a new independent
system. Scientific judgments remain attributed proposals or review decisions,
not conclusions inferred by structural database validation.

## 6. Hub integration alignment

A future capture or dashboard client (called Hub below) is a separate system.
These are integration requirements, not an implemented connection or an API
compatibility promise to a particular external project.

- Hub owns capture staging, capture revisions and delivery receipts. Research
  owns canonical knowledge after confirmed acceptance. A transferred capture
  references Research; it does not become a second editable knowledge record.
- The first accepted inputs remain text, Markdown and manually selected
  passages. Hub may stage other media independently. Audio processing, automated
  PDF ingestion, research jobs and publication are later capabilities.
- Manual commands and Hermes tools invoke the same deterministic application
  operations. Capturing, editing, reviewing and retrieving existing knowledge
  do not require a model call or a Hermes research job.
- Notes, claims, evidence spans and relations, assessments and review decisions
  retain immutable revisions, attributed provenance and exact dependency
  references. Hub displays projections of these producer-owned records.
- Claim assessment review is distinct from Hub result `reviewState`, execution
  status and publication release. No state automatically implies another;
  any future aggregate display needs an explicit mapping and dependency set.
- Balance and confidence describe the evaluated evidence and its limitations,
  not truth probabilities. API enum values and rating rubrics must be agreed
  jointly in the detailed contract; current display labels are not wire values.
- Private HTTPS is a later adapter around Python application operations. The
  local knowledge MVP can start without HTTP. Hermes remains the only agent
  harness; neither Hub delivery nor the HTTP adapter adds an agent loop.

### Contract requirements before connecting Hub

Authenticate and authorize every operation and referenced object in Research.
Keep the calling service identity distinct from the attributed human or agent;
an arbitrary client-supplied actor is not authority. Reading private source
passages and making review decisions require explicit permitted operations.

Mutations carry contract version, stable request/idempotency identity, payload
identity and expected revisions. Persist acceptance and its canonical references
atomically. Repeated identical commands return the original result; changed
payloads under the same key and stale revisions produce explicit conflicts.
After uncertain delivery, reconcile the original request before retrying.
HTTP status and ETag mappings belong to the adapter, not the domain model.

An assessment response must make its complete evaluated dependency set
inspectable: supporting, contradicting, qualifying and unclear relations;
exact source revisions and locators; appraisals and rationale; study overlap;
corpus/search coverage and omissions; assessment and review revisions; and
whether renewed review is required. A short UI summary may link to details,
but must not silently omit counterevidence or imply complete coverage. If rights
prevent disclosure, expose the limitation without leaking protected content.

### Remaining integration work

Operation names are working labels, not agreed HTTP paths or API enums.
The producer owns domain schemas and rating rules; clients map them after
contract review. Pagination, authorization, errors and mutation reconciliation
need explicit contracts before connecting an external dashboard.

Media attachments must remain staged until supported. Never silently discard
attachments or mark a partial capture transfer complete. Model-free operations
must not require an agent job merely to fit a client's execution schema.

## 7. Next steps

The original passage-to-claim pilot and local rubric are implemented. Continue
with the [structured knowledge plan](knowledge-structure-and-quality.md#7-incremental-implementation-plan)
alongside the approved extraction/source-view delivery:

1. Specify research-question associations, structured scope, evidence locators
   and citation-resolution contracts. Reuse existing identities and reviews.
2. Test one real question with a general claim, precise evidence and two or
   three Zettel. Uniform claim views derive cited bullet lists from the
   database.
3. Develop versioned author rules from author-selected samples and compare fixed
   writing tasks. Evaluate facts, synthesis and style separately; test larger
   model checks without treating them as human approval.
4. Verify migration and historical citations before expanding processing.
   Demonstrate useful incorporation of new evidence, not just successful runs.
5. Add bounded citation-network discovery and evaluate embeddings only against
   actual research/retrieval questions. Keep unselected findings outside the
   personal Zotero collection and retain provenance for external graph edges.

No separate historical fact-database concept was conclusively located during
the bounded earlier search. This records the proposal approved in the current
conversation, not a reconstruction of that older document.
