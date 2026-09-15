# Knowledge pilot contracts and assessment rules

The [structured knowledge contract plan](knowledge-structure-and-quality.md#2-one-database-explicit-schemas)
specifies pending extensions for research questions, contextual relevance,
entry metadata, structured claim scope and document citations. It also defines
graph/embedding ownership and authoring evaluation. These are target contracts;
the implemented types below remain the historical compatibility baseline.
Supporting/opposing source lists and graph edges already represented by domain
relations must be derived, not maintained as separate Markdown or graph records.

The [modular contract plan](knowledge-plugin-architecture.md#5-contracts-before-integration)
defines proposed intake, operation and change boundaries. Those plugin contracts
are not yet implemented public APIs. The deployed record contracts below remain
the compatibility baseline; future consumers must preserve their citation and
review semantics.

The [binding source-view specification](knowledge-source-view.md) defines the
forthcoming structured extraction and presentation contracts. Its ownership and
migration rules govern that revision; the implemented record contracts below
remain the baseline for preserving existing citations and reviews. Flat page
snapshots are historical input, not the required new document structure.

The [extraction module](knowledge-extraction.md) extends that planned contract
with Docling/Marker selection, explicit content issues and resumable jobs.
New evidence must pin its extraction revision and location; existing citations
keep their historical resolution rules. Extraction checks never determine
scientific confidence or replace the assessment rubric below.

Updated 2026-09-15, implemented for the server pilot. These local Python
contracts do not define a stable external dashboard API. The initial pilot
expanded to PDFs, Zotero import and an unstyled web interface.

The [September 15 product revision](knowledge-mvp.md#1-first-useful-outcome)
requires optional note creation, candidate reconciliation and sole Zotero source
ownership. These operations are present in the application. See the
[verification limits](README.md#historical-evidence-limits).

## Records and ownership

Every record has a stable UUID, positive revision, batch, server-attributed
actor,
timestamp and a strict typed payload. Unknown payload fields fail validation.
Source, Claim, Evidence, Assessment, Note and Review are separate record kinds.
Only the owning module writes its kind through the internal revision ledger.

Current sources retain Zotero server/library/item and attachment identities,
original and clean PDF hashes, immutable extracted pages and extraction
metadata.
Only Zotero owns editable bibliography and PDFs. Historical source revisions
remain readable, including their old metadata; new legacy sources are rejected.
The PDF derivative removes only a manually inspected curator cover. Citation
pages always refer to the original PDF, with an explicit clean-page offset.
Unchanged PDFs reuse one attachment. Every page enters a bounded extraction
chunk; absence of a useful claim is an allowed result. Unknown bibliography or
study overlap stays unknown. A curator label is not bibliographic authority.

Claims specify proposition, scope and qualifications. Evidence references an
exact source revision, original PDF page and exact quote, plus a claim revision,
relation, rationale, directness, methodology and limitations. Whitespace-only
matching may recover the original span; changed wording and ambiguous matches
fail. Structural citation validity does not verify the scientific inference.

Notes have one of four kinds: inbox, source, permanent or wiki. Their references
pin revisions. Wiki inline tokens `[UUID@revision]` must match those references.
The same note-edit operation is used by manual clients and the HTML interface.
Imports do not automatically create notes. Reconciliation accepts a distinct
claim, reuses an explicitly supplied claim reference, or logs a skipped
proposal.
Exact duplicate evidence is rejected across equivalent source migrations.
A separate passage check flags unsupported attribution before acceptance;
it is another fallible model judgment, not proof of factual correctness.

Consolidation revises existing permanent notes and wiki articles only. It pins
the supplied context, preserves cited entities and logs a proposal and text
diff.
Human-authored or previously approved notes are not automatically replaced.

## Assessment rubric

Assessments reference the claim and **every current evidence relation** for that
claim. They include balance, confidence, rationale, coverage and limitations.
Relation counts never calculate balance or confidence.

| Value | Rule |
| --- | --- |
| `open` | Evidence is missing, unclear or insufficient |
| `mostly_supported` | Substantive support exists; explain its limits |
| `mixed` | Actual support and contradiction exist within scope |
| `mostly_contradicted` | Substantive counterevidence exists |
| `low` confidence | Important method or coverage gaps remain |
| `medium` confidence | Main inference is supported; material gaps remain |
| `high` confidence | Direct, sound evidence; alternatives explored |

Confidence is confidence in the assessment, including a contradictory
assessment,
not the probability that a proposition is true. Thresholds are explained human
judgments, not numeric scores. The convenience sample normally warrants low
confidence. The validator enforces relation availability and empty-evidence
rules;
it cannot certify methodological quality or sound judgment.

Examples: immediate quiz performance does not establish four-week retention.
An imprecise null result is unclear, not proof of no effect. Two papers
repeating
one experiment are not independent replications. A review can overlap with its
primary studies. A qualification alone does not make a supported result mixed.

The cross-source pass inspects the first body page and one lexical candidate
page from each other document. Its candidate page list and search summary are
retained on the server. This is a limited search, never a systematic review or
scientific consensus. Empty additional evidence is an allowed outcome.

## Review and revisions

Model output starts `proposed`. The private human boundary may record
`reviewed`,
`revise` or `rejected`, with a mandatory comment, exact target and transitive
dependency set. Reviewed does not mean true. The agent boundary cannot approve
its own output. The pilot HTML boundary uses a configured human actor;
this is not a multi-user authentication system.

Review state is derived. A changed target/dependency or new evidence for an
assessment yields `needs_review`. Prior reviews and assessments remain readable.
An old review is not copied to a new revision. Assessment edits must refresh the
complete evidence set. Notes that cite stale assessments also require review.

Each mutation has a stable request ID and a hash over operation, actor, batch
and
typed payload. Same ID plus same content returns the original references;
changed
content conflicts. Expected revisions enforce optimistic edits. Domain mutations
and their receipts commit atomically. A failed claim/evidence contribution rolls
back together; an already registered source can remain for a resumed import.
`GET /api/requests/{id}` reconciles uncertain delivery without an
agent run. The private HTML adapter maps missing/conflict/validation to
404/409/422.

Revisions reject UPDATE and DELETE at the database level. There is no public raw
record mutation endpoint. The pilot database owner remains technically able to
alter its own schema; this is integrity protection, not adversarial isolation.

## External effects and pilot limits

Temporary PDF preparation and Zotero import precede database acceptance. They
cannot share a PostgreSQL transaction. Source hashes and Zotero attachment
identities allow retry reconciliation. A failed database command may leave a
Zotero item awaiting acceptance. Private model requests, responses and pending
processing snapshots support audit and resume; they are not editable literature
records. Completed imports remove their pending preparation snapshots.

Zotero provides the configured library and imported PDF attachments.
Library synchronization is managed by Zotero, not by this application.
Bibliography is extracted from supplied document versions, not independently
resolved against DOI registries. Keep metadata warnings visible during review.

This version has no remote Hub authorization, multi-user permissions, schema
migration framework, autonomous monitoring, general ingestion UI, fully accepted
structured extraction, per-record
deletion UI or production backup schedule. Database/file/Zotero test state is
isolated for later cleanup. The dashboard contract remains a separate task.

## Prompting references

The implementation uses short versioned task prompts, a schema, explicit
unknowns,
examples, no tools during extraction, and local validation with a bounded repair
attempt. Hermes owns the Luna provider connection and authentication.
Prompt-only
JSON plus validation is not represented as guaranteed model-side Structured
Outputs.

- [OpenAI prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [Hermes Python library](https://hermes-agent.nousresearch.com/docs/guides/python-library)
- [Psycopg transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)
- [Zotero connector server](https://www.zotero.org/support/dev/client_coding/connector_http_server)
