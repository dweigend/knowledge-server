# Personal knowledge management concept

The September 15 [structured knowledge and authoring decisions](knowledge-structure-and-quality.md)
govern the next knowledge-quality work: typed database schemas and metadata,
research relevance, general claims with precise evidence, citation networks,
derived embeddings and the author's author rules. Together with the
[modular workflow](knowledge-plugin-architecture.md), they supersede older
assumptions below about mandatory source notes, separate archives or generic
shared kernels. They are plans, not a deployment record.

The [binding source-view specification](knowledge-source-view.md), approved on
2026-09-15, governs the next article-view delivery and supersedes conflicting
presentation or architecture proposals here. This broader concept does not
require additional infrastructure for that delivery.

Updated: 2026-09-14. Status: documented target architecture, not a deployment
record. This historical concept preserves design rationale; the narrower
module specifications take precedence where they disagree.

The [approved MVP and claim assessment](knowledge-mvp.md) records the first
delivery scope, evidence-rating dimensions and remaining contract work.
It narrows implementation order without replacing this target architecture.

## 1. Purpose and scope

Build a personal, source-based knowledge system that makes existing material
usable for thinking, research and publication. It should collect books,
literature, conversations, personal ideas and current signals; preserve their
origins; support a connected Zettelkasten and knowledge wiki; and produce
traceable research briefs and scientific essays.

**Hermes Agent is the central agent harness on the host.** It owns the agent
loop for knowledge work: interpreting requests, planning work, assembling
context, selecting skills, invoking tools and producing source-based results.
Recurring research and knowledge work should run through this same harness.
PostgreSQL preserves the knowledge state; Zotero manages literature; reusable
deterministic commands enforce the information contracts.

The deployment target is a **Linux server without a GPU**. Required extraction,
database, retrieval and publication tools must run on its CPU. Hermes uses the
configured hosted model provider; the server does not need a local large-model
runtime. Optional extensions need explicit CPU resource and privacy evaluation.

Software-development infrastructure and podcast generation are outside this
research system. Podcast production is a separate system that may consume
released research documents through an explicit content contract. Git hosts
software and reviewed configuration; private knowledge remains outside Git.

The first useful outcome is a reliable cycle:

```text
Capture → preserve source → extract → connect → review → retrieve → reuse
```

The system should help the user find and develop knowledge already collected.
Daily unattended publishing comes after this cycle works with a small corpus.

## 2. Decisions, proposals and observed baseline

### Binding decisions

- **Hermes is the central agent harness for server-side knowledge work.**
  Web UI, Matrix, Codex and recurring triggers reach the same Hermes runtime
  for agent-assisted tasks. Reuse its agent loop, sessions, skills, tools and
  scheduler; do not build a competing knowledge-agent orchestrator.
- **The research deployment is Linux and CPU-only.** No GPU runtime is a
  prerequisite. Required tool dependencies need Linux resource acceptance.
- **Podcast production is an independent system.** Narration preparation,
  speech generation, audio revisions and podcast delivery have separate
  ownership, jobs and deployment. Research releases cited text and metadata.
- **Research modules have explicit responsibilities and contracts.** Skills
  orchestrate them; modules own their domain rules and writes. A shared agent
  harness does not merge their business logic into one module.
- **PostgreSQL is authoritative for the planned central knowledge system.**
  Note bodies use Pandoc-Markdown; structured records hold evidence anchors,
  claims, relationships, review decisions and complete revision history.
- **Zotero remains authoritative for literature management.** Central records
  reference Zotero identities and retain versioned bibliographic snapshots;
  they do not establish a competing editable literature catalog.
- **Markdown exports provide application-independent access and portability.**
  They are derived snapshots, not a second independently editable master.
- **All committed knowledge states remain reconstructable.** History includes
  source versions, evidence, links, decisions and deletions as well as prose.
- **Versioning, portable export and disaster recovery are separate duties.**
  Database and original-file backups need a verified restoration procedure.
- **Every interface uses the same versioned information contracts.** Matrix,
  the separately developed web interface, Codex and scheduled jobs are equal
  clients. The database itself does not replace those contracts.
- **Reuse Hermes and Open Research Lab.** Extend existing capabilities and
  scientific models instead of introducing another agent framework or a
  parallel research system.

This updates the earlier suggestion that Markdown files alone should be the
authoritative knowledge store. It also supersedes earlier OpenClaw and Trilium
directions. Matrix is an available channel, not the organizing principle of
the system.

### Historical design context

The original design targeted a single-user Linux deployment with Hermes,
PostgreSQL and Zotero. It also considered optional research skills, channels
and text publication. Those integrations are proposals unless explicitly
identified as implemented in the [documentation index](README.md).

Private host inventories, conversation exports and deployment reports are not
part of this repository. This concept is not a reproducible benchmark or proof
that a fresh installation has been verified.

## 3. Architecture and ownership

```text
Web UI / Matrix / Codex / recurring triggers
                    │
       authenticated adapters + request validation
                    ▼
       HERMES AGENT HARNESS ON THE HOST
       gateway and agent loop · provider and model
       sessions and context · skills and tools
       planning and delegation · research scheduler
                    │
       tool calls and structured knowledge proposals
                    ▼
       MODULAR DETERMINISTIC RESEARCH APPLICATION
       sources · ingestion · evidence · notes
       review · retrieval · text publication
       common contracts, revisions and atomic writes
                    │
         ┌──────────┼──────────────┐
         ▼          ▼              ▼
    PostgreSQL   file archive   Zotero Web API
    knowledge    originals      literature
    and history  and artifacts  authority
         └──────────┼──────────────┘
                    │
       released research text → HTML / LaTeX / Markdown
                    │
       versioned content package for independent consumers
```

### Hermes owns agent execution

All agent-assisted knowledge workflows execute through Hermes: book and chat
analysis, research, proposed Zettel and wiki updates, evidence-based answers
and briefing synthesis. The configured language model
is an engine inside this harness; changing Luna later does not change the
information contracts or create another workflow runtime.

Hermes assembles the relevant context using knowledge-retrieval tools, runs
the skill's scientific procedure, coordinates bounded delegated work where
useful, and calls deterministic commands for extraction, evidence handling,
validation and publication proposals. Its native sessions and execution
controls provide the interaction lifecycle. Human scientific review remains
an explicit domain decision, distinct from permission to execute a tool.

The research application's modules are Hermes's durable, validated tool surface.
Each module enforces its own domain contracts and writes; a small shared kernel
supplies identity, revision and transaction conventions. These modules do not
independently plan research, call models or run autonomous agent loops. Open
Research Lab contributes scientific capabilities and models used through them.

### Equal interfaces, one agent harness

The web interface and Codex send agent requests through a verified Hermes
control surface. Matrix uses the Hermes gateway's messaging adapter. Recurring
agent work starts from the Hermes scheduler. Adapters preserve authenticated
identity and normalize requests into the same knowledge contracts, regardless
of the transport's native message format.

There are two deliberately different operation paths:

- **Agent work:** client/trigger → Hermes → knowledge tools → versioned result.
- **Deterministic interaction:** manual edits, review decisions, record views
  and exports → the same validated knowledge commands, without requiring an
  LLM turn for every button or database read.

Both paths share permissions, entity/revision IDs and domain rules. The UI
does not acquire a separate research agent. Codex is a client of server Hermes
for knowledge tasks; software-development execution is outside this concept.

This is a logical separation of responsibilities, not a requirement to deploy
each box as a service. Start with Hermes plus a small application boundary and
reusable commands. Expose those commands as Hermes tools or skill-invoked CLI
operations, with an API for deterministic client interaction where needed.
Business rules live in code rather than in individual chat prompts.

### Example: connect a new paper to the existing wiki

1. The user submits the paper and research question through any supported
client.
2. The adapter validates identity/input and creates a common processing request.
3. Hermes retrieves relevant notes, selects the literature/evidence skill and
   invokes source acquisition and extraction commands.
4. Hermes submits claims, links and an article proposal through Evidence and
   Notes. They validate source anchors, scope and base revisions, using Sources
   to resolve citation identities; Review assesses the pinned revision set.
5. The result is saved as a versioned proposal awaiting the author's review. The
UI
   or Matrix/Codex response refers to the same request, run and object IDs.
6. An explicit review command accepts or edits the proposal. Only the accepted
   state becomes input to research publication or a released content package.

### Module boundaries

The application is a modular composition, not one general knowledge manager.
Separate source/catalog integration, ingestion/extraction, evidence, notes and
relations, review, retrieval and text publication. Each owns its domain tables
and exposes typed operations; another module cannot write those tables directly.
Application commands coordinate necessary transactions through the shared
unit-of-work contract. No separate service or database per module is required.

See [research modules and inspected skills](knowledge-system-modules.md) for
responsibilities, operation contracts, dependency rules and reuse decisions.
See [the independent podcast boundary](podcast-system-boundary.md) for the
downstream content contract. Podcast state is absent from the research schema.

| Area | Authority and responsibility |
| --- | --- |
| Bibliography | Zotero: items, creators, editions, collections |
| Citation mapping | PostgreSQL: source IDs, Zotero IDs and citation keys |
| Bibliographic snapshots | PostgreSQL: exact imported metadata versions |
| Originals | Immutable archive: files, exports and raw fetched content |
| Knowledge | PostgreSQL: notes, wiki and revisions |
| Published evidence | PostgreSQL: anchors, claims, links and review history |
| Research drafts | Open Research Lab SQLite: project-local working state |
| Agent execution | Hermes: model loop, skills, tool calls and coordination |
| Agent context | Hermes: sessions, operational memory and scheduler state |
| Search/text rendering | Derived indexes, embeddings, HTML and research PDF |
| Portable snapshots | Markdown packages derived at a central checkpoint |

Store core identities and relationships relationally, using foreign keys and
uniqueness rules. JSONB is suitable for variable provider metadata, not a
substitute for integrity rules on evidence or citation identities. These are
documented PostgreSQL capabilities; the proposed domain design is our own.
See [constraints](https://www.postgresql.org/docs/current/ddl-constraints.html)
and [JSON types](https://www.postgresql.org/docs/current/datatype-json.html).

Notes edited in exported files must return through an explicit import command
with their base revisions. Avoid automatic bidirectional directory syncing.
The parallel UI must read and write the same commands; it must not acquire its
own authoritative copy of note content.

## 4. Information model and shared contracts

### Core records

| Record | Purpose |
| --- | --- |
| Source | Stable identity of a work, conversation or other origin |
| Source version | Exact imported metadata/content, acquisition time and hash |
| Evidence anchor | Inspectable page, paragraph, message or time-range span |
| Claim | Proposition with scope, qualifications and linked evidence |
| Note | Fleeting idea, source note, Zettel, structure note or wiki article |
| Relation | Directed typed link, rationale, endpoints and review state |
| Review decision | Attributed decision about specified revisions |
| Processing run | Request, inputs, workflow/tool versions and outcomes |
| Change batch | Atomic revisions and reconstructable knowledge checkpoint |
| Artifact | Versioned research document, bibliography or export |

Give every record a stable opaque ID, independent of title, filename, channel
and citation key. UUIDs are the proposed initial choice. A source ID represents
identity; a source-version ID represents the material actually read. A new
edition, translation or preprint-to-journal transition requires an explicit
identity decision rather than an automatic merge.

### Three common information contracts

The following field sets are proposed for contract version 1. They are a design
specification, not implemented schemas or promised endpoint names.

**Knowledge input:** contract version; input ID and kind; content or immutable
file reference; origin and external identity; source timestamps if known;
acquisition timestamp; scope; actor; deduplication identity.

**Processing request:** contract version; request ID; operation; revision-pinned
input references; parameters; idempotency key; authenticated actor and scope;
expected base revisions for edits.

**Processing result:** contract version; request/run IDs; execution state;
output IDs and revisions; claims, anchors and relationships where relevant;
review state; checkpoint; structured errors and warnings.

Begin with operations for capture, source ingestion, note proposal/editing,
review and search. Each operation has a module-specific payload schema inside
the common envelope. Literature synthesis uses research contracts; downstream
media processing has a separate contract and result schema.

Common rules:

- Validate shape, identities, permissions, references and state transitions
  before writes. Validate LLM output against the same domain rules.
- Determine actor and allowed scope from authenticated credentials. A client
  field or an LLM instruction cannot grant itself access.
- Preserve transport origin separately from scholarly provenance. A paper
  delivered through Matrix is supported by the paper, not by the Matrix event.
- Pin inputs to revisions. Resolve search at an explicit checkpoint and return
  source versions and locators with the answer.
- Retry by idempotency key. The same key and payload returns the recorded
  result; reuse with changed payload is a conflict. Identical text alone is not
  proof that two personal notes are the same idea.
- Separate run states such as queued/running/succeeded/failed/cancelled from
  content states such as suggested/accepted/rejected/needs-review.
- Return stable machine-readable error codes, including invalid input, missing
  source, permission denial, revision conflict and provider failure.
- Version the contract independently of object revisions and database schema.
  Define compatibility tests and migrations before changing a public shape.

A Matrix capture, a web-form capture and a Codex command should produce the
same kind of input and note record. They may have different origin fields and
response presentations. A Matrix reply may give a short acknowledgement and
object link; the UI may show an editable proposal and evidence panel. Both
must expose the same run ID and review state.

Use Hermes's native API/gateway as the agent entry point and attach the domain
request/result contract to its tool workflow. The native chat format alone is
not the complete knowledge contract. The documented API supports authenticated
agent requests; the installed implementation and actual enabled endpoints must
be checked before integration. No MCP layer is required for HTTP or CLI calls.
See [Hermes API Server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server).

## 5. Complete revision history and concurrent editing

### Proposed revision model

Use stable entity identities with immutable, append-only revision records and
a transactionally maintained current head. Full revision snapshots are the
simple initial recommendation; compressed diffs can wait until real volume
justifies them. An ordinary application role cannot update or delete historical
revisions. Schema migrations must preserve their original payload meaning.

Each revision records:

- Entity and revision IDs, predecessor revision and change-batch/checkpoint ID.
- Complete versioned payload, including reference targets and tombstone state.
- Server-recorded UTC timestamp; separately, source event time where known.
- Responsible human or agent identity, initiating user, processing run and
  workflow/model/tool versions when relevant.
- Change reason, operation and schema/contract version.

This applies equally to note text, bibliographic snapshots, source versions,
extracted text, anchors, claims, relations, scopes and review decisions.
Files remain immutable and content-addressed; replacement creates a new
source version and retains the earlier file. Review decisions pin the exact
claim, note, evidence and relationship revisions they assess.

Deletion creates a tombstone revision. Earlier states still resolve to the
previous content. Reverting an edit creates another revision referencing the
chosen earlier state; it does not erase intervening changes. Historical access
still requires current authorization, so an old public scope cannot bypass a
later privacy restriction.

The retention promise begins with states actually captured or committed in
this system. Polling an external service cannot recover intermediate versions
never observed, or reconstruct already lost history. Preserve imported raw
exports and record this coverage limit explicitly.

### Consistent whole-system reconstruction

Commit related changes as one short PostgreSQL transaction: new revisions,
head updates, review invalidations and the change-batch record either all
succeed or all roll back. External retrieval and LLM generation happen before
this transaction, with base revisions checked again at commit.

For the initial personal system, propose a single locked checkpoint row to
serialize final knowledge commits and allocate an ordered checkpoint inside
the transaction. This is a small application mechanism to review during schema
design, not a PostgreSQL temporal-table feature. Do not use a standalone
sequence or wall-clock timestamps as proof of commit order.

To reconstruct checkpoint N, select the latest revision of every entity at or
before N, apply its tombstone state, and follow revision-pinned dependencies.
The transaction snapshot used for an export must match its manifest checkpoint.
An article therefore resolves to the historical evidence and bibliographic
versions it used, even if current sources or titles have changed.

PostgreSQL MVCC and transaction isolation provide concurrent transaction
visibility; they do **not** provide permanent application-level history.
Consistent multi-query exports need an appropriate snapshot, such as a
read-only repeatable-read transaction. See
[MVCC](https://www.postgresql.org/docs/current/mvcc-intro.html) and
[transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html).

### Protection against lost updates

Every edit carries expected base revisions, including relevant dependencies.
Inside the write transaction, compare them with locked current heads. If a
human changed the note while Hermes was preparing a proposal, reject the stale
write with a revision conflict and retain the proposal for comparison or
explicit rebase. No silent last-writer-wins behavior.

Unique idempotency records prevent retries from committing twice. A proposed
transactional publication/outbox record can make committed work discoverable
to delivery jobs; retries then deliver the existing artifact rather than
regenerate knowledge. This does not claim exactly-once delivery by an external
chat or email provider.

## 6. Literature, Zotero and scientific writing

### Citation identity contract

For each Zotero-backed source, preserve these distinct identities:

| Identity | Meaning |
| --- | --- |
| Internal source ID | Stable knowledge-system identity |
| Zotero library identity | User/group library and numeric library ID |
| Zotero item key | Entry identity within the specified library |
| Zotero version | Observed item version and library sync checkpoint |
| Citation key | Controlled bibliography identifier in Pandoc-Markdown |
| Source-version ID | Exact imported metadata/content used as evidence |

Make the library-type/library-ID/item-key tuple unique within the registry.
Associate citation keys with source identities in an explicit namespace;
reject ambiguous keys and preserve aliases when an approved key changes.
Exported BibLaTeX/BibTeX entry keys or CSL-JSON `id` fields must match the keys
in the exported note texts. A title-based key must never be the database ID.

Use a controlled server citation-key registry and preserve approved imported
keys. Better BibTeX keys from existing exports can be reused if their mapping
is checked; they are not a native field guaranteed by the Zotero Web API.
Choose the explicit key handover and test round trips before autonomous imports.
The research server does not depend on a running bibliography application or
an automatic export plugin. See
[citation keys](https://retorque.re/zotero-better-bibtex/citing/).

### Server catalog integration

Inventory and back up the existing library and legacy database before migration.
Import a small batch first; check authors, dates, editions, DOI/ISBN, duplicate
matches and attachments. Keep a recovery report rather than silently dropping
unreadable legacy entries.

Use the Zotero Web API for the synchronized online library on the server.
Start with scoped reads; reviewed literature additions can later use a
controlled write path. The inspected Zotero skill targets a local application
API; its helper is not an already implemented Web API server adapter. Reuse
the citation identity rules, then extend the catalog integration deliberately.
See [Web API basics](https://www.zotero.org/support/dev/web_api/v3/basics).

Record item and library versions, fetch incremental changes, process deletions
and advance the synchronization checkpoint only after a consistent successful
batch. Preserve each version used by the knowledge system. Zotero writes must
use its version preconditions and handle conflicts rather than overwrite newer
metadata. Neither a remote deletion nor a changed annotation removes centrally
retained historical evidence. See
[Zotero synchronization](https://www.zotero.org/support/dev/web_api/v3/syncing).

Zotero metadata synchronization and attachment storage are separate choices.
Decide Zotero Storage versus a compatible attachment/WebDAV arrangement after
inventory. Server processing requires explicit access to the actual files;
having bibliographic metadata alone does not establish PDF availability.

### Pandoc-Markdown and publication

Use one documented Markdown dialect with citations, locators, footnotes and
ordinary links. For example, this fictional key must resolve in the supplied
bibliography:

```markdown
The argument has a limited scope [@example2026, pp. 33-35].[^scope]

[^scope]: This is an explanatory qualification, separate from the citation.
```

Pandoc can process citations against BibLaTeX/BibTeX or CSL-JSON and generate
HTML and LaTeX. It does not synchronize the wiki and Zotero. A pinned rendering
configuration and bibliography snapshot should accompany every publication.
See [bibliographic data](https://pandoc.org/MANUAL.html#specifying-bibliographic-data),
[citation syntax](https://pandoc.org/MANUAL.html#citation-syntax) and
[footnotes](https://pandoc.org/MANUAL.html#footnotes).

The parallel UI must edit this syntax without loss and render citations through
the agreed citation-aware text-publication module. A generic Markdown preview
is insufficient for the publication view. Choose and smoke-test a Linux CPU
LaTeX toolchain; do not assume that inspected skill dependencies are installed.
Exact evidence anchors remain structured records even when a rendered citation
says only "pp. 33-35".

## 7. Zettelkasten, wiki and scientific review

Use several explicitly different note kinds:

- **Fleeting note:** quick capture of a question or idea without mandatory
  classification at entry.
- **Source note:** summary or excerpt tied to a specific source version and
  precise locators; separate quotation from paraphrase.
- **Permanent Zettel:** a coherent thought in the author's own words, linked to
its
  sources and to other thoughts with an explanation of the connection.
- **Structure note:** a curated route through concepts, open questions and
  relevant notes; more useful than an ever-growing folder hierarchy.
- **Wiki article:** a revisable synthesis of a subject, citing accepted evidence
  and retaining unresolved disagreement and uncertainty.

Treat atomicity as a guide to clarity, not an obligation to fragment every
paragraph. Stable IDs, meaningful links and structure notes draw on practical
Zettelkasten methods; their benefit with this corpus still needs evaluation.
See the [Zettelkasten introduction](https://zettelkasten.de/introduction/).

Represent relationships as directed PostgreSQL records with endpoint IDs,
revisions, type, rationale and review state. Initial types: supports,
contradicts, extends, contextualizes and applies. Distinguish a scientific
claim-to-evidence link from a conceptual note-to-note association. A shared
keyword or embedding similarity is only a proposed connection, not evidence
of support or contradiction.

Recursive relational queries can traverse these connections. Start without
Neo4j or another graph database; evaluate additional tooling only when a
demonstrated query or scale requirement exceeds this design. See
[recursive queries](https://www.postgresql.org/docs/current/queries-with.html).

Borrow the useful LLM-wiki pattern of preserving raw sources and repeatedly
improving linked syntheses, but adapt it to database authority and revisioned
review. It is an emerging design pattern, not proof that automatic wiki
compilation yields accurate scholarship. Hermes proposes an article delta;
deterministic code validates it; review determines its published status.
For the original pattern, see
[Karpathy's LLM wiki sketch](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

### Evidence rules

- Scholarly claims point to exact source spans, not merely a URL or bibliography
  entry. Record edition, printed page and PDF page separately where relevant.
- OCR and extraction are derivatives with tool/version metadata. Retain page
  mapping, uncertainty and extraction QA; structural completeness is not proof
  of correct content.
- Preserve claim scope, definitions, methods, population and limitations.
  Distinguish preprints, peer-reviewed work, opinion and personal hypotheses.
- Record negative results, contradicting evidence and gaps. A large reference
  list alone does not establish a systematic review.
- LLM proposals begin as suggested. Scientific publication consumes accepted
  claims and accepted evidence links, following Open Research Lab's review gate.
- Changes to a reviewed statement or dependency require a new review. Old
  acceptance remains historical; it does not transfer automatically to a new
  revision. Current views show affected material as needing review.
- Record technical validation and substantive review separately. A valid JSON
  shape or working citation is not evidence that an interpretation is correct.

Source viewing, selected-passage editing, a readable diff and a visible review
decision should be first-class UI capabilities. Preserve personal voice;
machine summaries must not silently become the author's authored Zettel.

## 8. Imports and recurring workflows

### Books and legacy literature

1. Inventory locations, formats, counts, editions and existing identifiers.
2. Preserve original files and legacy exports with checksums and import
manifests.
3. Import reviewed bibliography into Zotero; map it to central source IDs.
4. Extract chapter/page packages and record OCR or conversion quality.
5. Produce source notes, then selected Zettel and wiki proposals.

Reuse lessons from the existing jazz book extraction packages: chapter
structure, page locators and QA reports. General books require a consciously
adapted extraction path; do not assume a music-specific skill is universal.

### ChatGPT, Codex and Claude conversations

Acquire actual available exports and inventory their coverage before promising
a complete import. Preserve raw conversations, message order, speaker roles,
timestamps, attachments, branching/fork relationships and external IDs when
the format supplies them. Missing fields stay explicitly unknown.

Deduplicate exact export repetitions and forks carefully, preserving lineage.
Extract ideas, decisions, open questions, useful methods and pointers to
external sources. Keep the message range supporting each extraction. A user
decision, an assistant proposal and a later superseding decision are different
records. Historical facts suggested by an assistant require original-source
checking before use as scientific evidence.

Start with one topic and a bounded set of conversations. Review the resulting
decision timeline and a few Zettel before scaling to the whole corpus. Private
conversation content must retain its scope across search, exports and jobs.

### X and current information

Reuse the existing X archive and `x-research` workflow. Archived posts are
discovery signals; fetch and evaluate the linked paper or original source
before elevating a post into a scientific claim. Retain post identity,
acquisition time, original-source mapping and the reason it is relevant.

Use the archive's raw snapshots and preserve manual tags, notes and review
states. The inspected X skill has fixed paths and a coupled synchronization
bootstrap, so it needs configurable server storage and an explicit collector
contract. Keep collection, archived-input ingestion and claim verification
separate. A collector has one synchronization owner; research consumes its
versioned outputs. Paid API activity needs limits and monitored cost.

### Daily research briefing

Begin with selected themes and an explicit source registry: paper/preprint
feeds, publishers, trusted blogs and relevant X signals. Set inclusion criteria,
time windows and the handling of updated papers. A proposed run does:

```text
Collect → normalize/deduplicate → detect meaningful changes → retrieve originals
        → extract evidence → rank with rationale → draft → verify/review
        → save cited research briefing → release text → notify research clients
```

Preserve collection coverage and failures. Explain why an item matters and how
it connects to existing notes. Avoid regenerating a full briefing for unchanged
sources; report only meaningful findings, completion, actionable failure or
needed review. Do not let a failed provider look like "nothing new".

During the pilot, The user reviews each briefing. Later low-risk collection and
drafting can be scheduled, while the chosen publication policy remains explicit.
No autonomous acceptance of scientific claims is assumed by this concept.
Hermes executes the research skill and coordinates these steps. Collection,
retrieval, evidence and text publication are separate module operations called
by the skill, rather than agents each running their own model loop.

### Content handoff to independent systems

The research text-publication module may export a released, immutable document
package for another application. It includes accepted document revisions,
checkpoint, bibliography/citation mapping, source references, review state and
manifest hashes. A consumer failure cannot invalidate the research publication.

Podcast production consumes that package as an independent system with its own
jobs, revisions, permissions and lifecycle. Narration preparation and audio
production are absent from the research workflow and its data model. Only the
[boundary contract](podcast-system-boundary.md) is documented here; technology
selection and implementation belong to the separate podcast project.

## 9. Hermes harness and scientific tool integration

### Reuse the native agent lifecycle

The target has one central server knowledge-agent runtime: Hermes. Use its
existing model/provider handling, agent loop, sessions, skills and scheduling.
Implement knowledge-specific tools and procedures inside that runtime instead
of constructing a new model client, planner or independent research daemon.

Select and verify a native control surface for the parallel UI and Codex:
the HTTP API is suitable for HTTP clients; Hermes also documents gateway
protocols for richer interaction. Reuse supported progress, session and run
controls rather than recreating them. Endpoint availability and actual
installed-version behavior remain acceptance work. See
[programmatic integration](https://hermes-agent.nousresearch.com/docs/developer-guide/programmatic-integration/).

The central processing record should map the domain request/run ID to the
Hermes session and native execution ID when available. Native agent progress
and a committed knowledge revision are different events: an agent can finish
with a draft awaiting review, or encounter a stale-edit conflict. Record both
without inventing a second agent controller to reconcile them.

### Knowledge workflows as Hermes skills and tools

Proposed initial skills cover source ingestion/analysis, knowledge retrieval,
Zettel/wiki proposals, literature synthesis and research briefings. Their
instructions refer to the shared scientific procedures and tool contracts.
The tools perform identifier lookup, acquisition, extraction, citation mapping,
evidence persistence, search and revision-safe writes. Rendering and export
remain deterministic text-publication commands at the appropriate step. The
skills coordinate separate modules and do not contain those modules' database
writes, schema rules or review transitions.

Hermes's bounded memory is for preferences and operational context, not a full
knowledge corpus. Session search helps retrieve Hermes conversations; it is
not already an importer or search engine for all external chats. See
[memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/)
and [skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/).

Reuse the Hermes scheduler for recurring research skills instead of immediately
adding another agent scheduler. Its isolated scheduled sessions are not a
filesystem or container security boundary. Database backup scheduling may use
standard operating-system mechanisms and must not depend on an LLM deciding
to execute it. See
[scheduled tasks](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron/).

### Open Research Lab is the scientific capability layer

Open Research Lab already separates semantic judgment from deterministic
schemas, provider routing, normalization, evidence handling and review. Reuse
these models and capabilities; preserve its separation between discovery,
screening, evidence extraction and accepted synthesis. Installed plugin code
does not become a writable corpus directory. The inspected `open-research-lab`
repository describes this in `docs/architecture.md`; relevant source locations
and skill mappings are recorded in the
[module reuse assessment](knowledge-system-modules.md#4-inspected-skill-reuse).

Its current Codex plugin packaging is not assumed to run unchanged as a Hermes
skill. Adapt the relevant workflow instructions to Hermes, reuse deterministic
commands and models, and verify their server runtimes and inputs/outputs.
On the server Hermes owns semantic execution; Open Research Lab supplies the
scientific procedure and validated capabilities. Existing local Codex research
projects can continue to publish reviewed packages through the agreed boundary.

Concrete reuse points include source/evidence/claim models, typed locators,
citation audits, versioned application envelopes and storage ports. Scientific
relations keep supports/contradicts/qualifies/uncertain; conceptual note links
have their own types. The commands currently instantiate SQLite implementations
directly, so persistence integration still requires explicit work.

Existing append-only audits and parent-linked synthesis drafts are useful,
but the general entity repository uses upserts and does not preserve complete
historical payloads for every entity. Its generic JSONL export is not a
review-filtered publication package. Do not present either capability as
already satisfying the central full-history contract.

**Recommended first integration, still to be approved:** retain existing
project-local SQLite working state and publish reviewed, revision-pinned
research packages through the central contracts into PostgreSQL. Record project,
object and revision mappings plus package hashes. Local project drafts are
research inputs; published research packages are immutable source material for
centrally editable Zettel and wiki articles. Corrections to published research
arrive as a new reviewed package revision. They do not silently rewrite an
existing central note or transfer its review status to changed evidence.

The publication contract must explicitly include project and local entity IDs,
release revision, manifest hash, source versions, original-object references,
accepted claims/evidence/relations and citation audits. Use distinct local and
central identities with a recorded mapping. The existing export requires an
extension for this purpose; import must be idempotent and transactional.

Full central history begins at ingestion/publication. A mutable legacy SQLite
project cannot promise reconstruction of unrecorded intermediate local drafts.
If those drafts become part of the required central history, capture complete
versioned payloads at each change or implement the persistence migration first.
This boundary must be accepted explicitly, rather than hidden behind the word
"synchronization".

The alternative is a deliberately designed PostgreSQL persistence adapter for
the research capabilities. It requires inspection of ports, transaction/review
semantics and migrations; it is not achieved by changing a connection string.
Choose the boundary before broad imports. Do not maintain two independently
editable authoritative copies of the same published note or claim.

Hermes's internal SQLite/session stores, Zotero's own database and the X archive
can keep their separate operational responsibilities. PostgreSQL selection
does not mean replacing every existing database. The independent server path
also needs a Zotero Web API adapter; the present research architecture describes
a local application API/Connector integration.

## 10. Search and answer quality

Start with PostgreSQL full-text search, identifier lookups and filters for
topics, source kinds, status, dates and scope. Select language-aware text
configuration for German/English material and return passages with locators.
See [full-text search](https://www.postgresql.org/docs/current/textsearch-intro.html).

Follow typed links when a question calls for conceptual context, supporting
evidence or disagreement. Answer from retrieved source/note revisions, expose
coverage limits, and say when the available material cannot support an answer.

pgvector is a possible later PostgreSQL extension for semantic and hybrid
retrieval. Embeddings remain rebuildable derivatives tied to content revision,
model and configuration. The project's own documentation describes combining
vector and full-text retrieval; the benefit for the author's corpus is **not yet
benchmark-tested**. See
[pgvector hybrid search](https://github.com/pgvector/pgvector#hybrid-search).

Prepare a small evaluation set of real questions with expected sources,
including exact quotations, German/English concepts, contradictions and
historical decisions. Compare retrieval quality and latency before adding
embeddings or more infrastructure. Neither Qdrant, Neo4j nor a separate search
cluster is justified for the initial system by current evidence.
Measure CPU time, peak RAM and retrieval latency with the pilot corpus. Local
embedding generation is optional and disabled until its CPU cost is accepted;
a hosted adapter requires a separate privacy and usage decision.

## 11. Portability, backup and restoration

### Three separate guarantees

| Guarantee | Purpose | Insufficient alone for |
| --- | --- | --- |
| Revision history | Reconstruct retained knowledge | Recovery after disk loss |
| Markdown export | Read/transfer without the UI | Full operational recovery |
| DB/file backup | Recover after failure | Domain history and readable notes |

### Proposed portable export package

Export a consistent checkpoint to an independent destination, containing:

- One readable Markdown file per exported note, with stable ID, kind, revision,
  checkpoint, timestamps, scope and source/relation references in front matter.
- Relative links named by stable IDs, with readable titles as labels.
- Bibliography and citation-key mapping pinned to the same exported state.
- Structured companion records for anchors, claims, typed relationships, review
  decisions, source versions and tombstones, without requiring the web UI.
- A manifest with schema/export version, checkpoint, included scopes, counts,
  hashes, file references and explicitly omitted material.
- Links to preserved originals, or an explicitly selected original-file bundle.

Define a readable current-state export first, then an archival history export
with earlier revisions. Do not call a current-state-only folder complete
historical preservation. A portability import needs explicit ID/conflict and
review handling; exported files do not silently overwrite newer database heads.

### Real recovery

Use PostgreSQL-native backups and separately back up the immutable originals,
configuration needed for restoration, citation manifests and relevant service
state. Keep credentials and encryption keys in the private recovery procedure,
outside Git and separate from ordinary agent access.

Logical `pg_dump` backups are a practical initial proposal; include required
roles/global configuration through a separate documented mechanism. Dumps do
not include arbitrary original files. If the accepted recovery-point objective
requires recovery between dumps, evaluate physical base backups plus continuous
WAL archiving and PITR. Choose one documented backup chain and its tooling
after deployment-version and operational review. See
[backup options](https://www.postgresql.org/docs/current/backup.html),
[pg_dump](https://www.postgresql.org/docs/current/app-pgdump.html) and
[PITR](https://www.postgresql.org/docs/current/continuous-archiving.html).

Because originals are immutable, retain every file referenced by a selected
database backup/checkpoint and store a matching manifest. Garbage collection
must respect retained revisions and backups; deleting an unused current file
can otherwise break historical restoration.

**Unapproved starting proposal:** daily logical database backups and Markdown
snapshots, file backup after successful ingestion, an independent off-server
copy, and a monthly restore drill. Daily/weekly/monthly retention tiers are an
option, not a selected policy. Set intervals and retention from corpus size,
acceptable data loss, restore duration and NAS/offline capacity. No recovery
point, recovery time or retention guarantee has been accepted yet.

A restore drill must use an isolated empty target and verify database restore,
original-file hashes, reference integrity, citation rendering, current search
and reconstruction of a selected earlier checkpoint including a deletion and
review change. Record backup identifiers, recovered checkpoint, duration and
failures. Export success and NAS job success alone are not restore acceptance.

## 12. Access and operations

Use one authorization model for all clients and corpus scopes. Separate private
conversation ingestion, routine reading, draft creation, review/publication and
administration. Scope filters apply before retrieval and generation, including
relation traversal and exported snapshots.

Data scope also controls whether material may enter the hosted model provider.
Sensitive qualitative inputs require their separately approved private path;
the presence of a research skill is not permission to send raw transcripts.
The independent podcast consumer receives only its approved released package.

Keep agent workspaces and credentials limited to their jobs. Prefer private
LAN/Tailscale access for the pilot API and UI, with authenticated requests.
Matrix allowlists do not constrain filesystem access; the current Hermes
gateway still runs with the author's permissions. Containerization and network
restrictions require explicit setup and verification before broader unattended
operation. Do not give a research job NAS management credentials.

Log request/run IDs, workflow versions, source coverage, durations, failures,
retry state and model/API usage. Keep raw personal text and secrets out of
ordinary operational logs. Define per-run bounds and cancellation behavior.
Separate collection failure, invalid proposal, revision conflict, review pending
and delivery failure so each can be retried at the appropriate step.

Deployment requires verified backups, explicit permissions and recoverable
storage before unattended work. Host-specific storage administration belongs
outside this application repository.

## 13. Staged plan and acceptance criteria

Each stage produces a reviewable result before the next expands scope. Stage
durations depend on inventory and are intentionally not committed here.

### Stage 1: Inventory and contract pilot

Inventory the real Zotero library, legacy formats, a book, one chat topic, the X
archive and the parallel UI. Agree on contract version 1 and citation identity
ownership. Select a small mixed corpus and real retrieval questions.

Acceptance:

- Locations, formats, coverage and unknowns are recorded; originals are safe.
- Input/request/result examples exist for capture, source import, edit, review
  and search, with invalid-input and conflict examples.
- UI and Hermes integration owners agree on the same operations and states.
- A native Hermes entry point and initial knowledge skill/tool boundary are
  selected; no separate UI or knowledge-core agent loop is introduced.
- The Open Research Lab publication boundary and pilot source set are decided.

### Stage 2: Central persistence and history

Deploy the selected PostgreSQL version and a minimal deterministic application
boundary. Implement identities, revisions, checkpoint commits, evidence anchors,
scopes and optimistic editing. Configure backups before valuable bulk imports.
Connect a supervised Hermes skill to this command boundary early; the first
agent proposal should exercise real persistence, not a parallel temporary store.

Acceptance:

- A note, source, anchor, claim, relation and review change have attributable
  immutable revisions; a deletion preserves its prior state.
- A known earlier whole-system checkpoint reconstructs consistently.
- Two competing edits produce an explicit conflict without lost content.
- Repeating an idempotent request commits only once; failed batches leave no
  partial heads or orphaned evidence links.
- An initial backup restores on an empty isolated target with matching
originals.
- One supervised Hermes request produces a validated, revisioned proposal with
  request/run/session mapping and an explicit review state.

### Stage 3: Literature and publication round trip

Integrate a small Zotero collection and one extracted book chapter. Establish
versioned Web API reads, fixed citation mapping and Pandoc rendering.

Acceptance:

- Each citation resolves uniquely to a source and library/item identity.
- Metadata changes produce new source versions without rewriting old citations.
- Printed/PDF page anchors are inspectable; questionable extraction is visible.
- One note renders matching citations, footnotes and bibliography in web HTML
  and LaTeX/PDF, with unknown keys reported explicitly.
- A portable export remains readable and its bibliography reproduces the note.

### Stage 4: Connected knowledge and interface parity

Import the bounded chat topic and selected archived X items. Produce reviewed
Zettel, meaningful links and one wiki article. Connect web UI, Codex and Matrix
to the same Hermes harness for agent requests, and to common commands for
manual edits/review. Exercise the agent path from a supervised scheduled skill.

Acceptance:

- Chat-derived ideas retain message locators, speaker role and supersession;
  scholarly assertions point to checked external sources.
- The wiki separates source summaries, personal thoughts and accepted evidence.
- The same logical capture/edit/review request has equivalent domain behavior
  across clients, including validation, revisions and permissions.
- An equivalent research request from each client reaches Hermes and uses the
  same skill/tool contracts; status and resulting evidence are traceable.
- A changed dependency visibly invalidates current review without deleting its
  historical acceptance.
- The retrieval question set is evaluated against expected source spans; scope
  restrictions also hold for linked and historically retained material.

### Stage 5: Research briefing and content release pilot

Run collection, drafting and scientific review on a selected theme. Use Hermes
as the research harness and exercise the separate ingestion, evidence, review
and text-publication modules. Optionally export a released content package.

Acceptance:

- Briefing items have originals, locators, relevance rationale and coverage.
- Revised papers and duplicate signals are handled without duplicate knowledge.
- The released document has accepted paragraph/evidence links, a pinned
  bibliography, checkpoint and manifest hash.
- Provider and text-export failures are visible and resumable without rewriting
  previously accepted research.
- Research remains fully usable when every downstream media consumer is absent
  or unavailable; its failure does not change research run or review state.

### Stage 6: Scheduled server operation and expansion

Enable verified recurring research skills through server Hermes, maintain one
owner per collector/job and widen the corpus in controlled batches.

Acceptance:

- Permissions, enforceable isolation, usage limits and publication policy are
  accepted and tested; a scheduled session is not mistaken for a sandbox.
- A restart/retry does not duplicate a committed briefing or erase manual work.
- Notifications match the selected policy and emphasize actionable changes.
- A complete restore drill passes, including historical evidence and citations.
- Backup/export retention and recovery objectives are decided and monitored.
- Search evaluation determines whether pgvector or further tooling is needed.
- Required research tools pass Linux CPU smoke tests with agreed time/RAM
  bounds. No required command attempts to start a GPU runtime.
- Modules use public contracts and cannot overwrite another module's tables;
  podcast deployment/state has no dependency in the research runtime.

## 14. Decisions still needed

1. Zotero library/account location, online synchronization, attachment storage
   and the recoverable format of the old literature database.
2. Citation-key authority, namespace, import handover and treatment
   of works that are not Zotero-backed.
3. PostgreSQL deployment version/location, schema ownership and operational
   permissions; final checkpoint/revision implementation after review.
4. Open Research Lab integration: reviewed-package publication first versus a
   deliberate PostgreSQL adapter, including the authority of research drafts.
5. Version-1 contracts, verified Hermes control surface, initial skills/tools
   and the interface agreement with the parallel UI.
6. Pilot topic, source collection, real search questions and acceptable quality.
7. Chat export availability, actual import coverage and private corpus scopes.
8. Research sources, daily briefing time zone, length, review/publication policy
   and channel-specific delivery preferences.
9. CPU/RAM/time budgets for extraction, text rendering and optional embeddings.
10. Backup/export intervals, retention, off-server/offline destination, recovery
    objectives and verified restore ownership.

The next planning result should be a small contract-and-corpus pilot with these
ownership decisions, rather than a simultaneous rebuild of every existing tool.

See the [independent architecture review](knowledge-architecture-review.md)
for findings, their resolution and remaining implementation verification.
