# Structured knowledge and authoring quality

Decision date: 2026-09-15. Status: approved direction and implementation plan.
The schemas below are requirements to refine before migration, not deployed
tables, final API fields or a claim that model quality has been established.

This document owns the next knowledge-model and authoring-quality decisions.
It extends the [modular workflow](knowledge-plugin-architecture.md) and
[MVP](knowledge-mvp.md). The [source-view specification](knowledge-source-view.md)
owns document presentation; the [extraction specification](knowledge-extraction.md)
owns source transcription. Existing [contracts](knowledge-contracts.md) remain
the migration baseline for historical citations and review decisions.

## 1. Product outcome and selection

Develop the author's arguments, research and reusable writing. Prefer precise,
well-written Zettel that can support essays and presentations. A large imported
library or more generated text is not itself a useful outcome.

Separate broad discovery from the personal knowledge collection:

| State | Meaning |
| --- | --- |
| Discovered | A scoped search candidate, not selected personal literature |
| Selected | Chosen for a research question; Zotero ownership must be verified |
| Processed | Processing completed, possibly without a useful contribution |

These are intake and selection states, not scientific approval. Record personal
reading separately from machine processing; never mark a paper as read by the
user
because extraction or summarization succeeded. Partial reading may identify
sections or pages. Processing failure is not a successful no-contribution
result.

Associate relevant entries with a research question or work context. Store the
role and short relevance rationale on that association: a source may be central
to one question and background for another. Start with central, background and
counterposition roles; a counterposition still needs its evidential relevance
checked. Avoid one global relevance score. Unassigned personal ideas remain
valid captures; do not fabricate a research question merely to accept them.

Landscape mapping may use many discovered candidates without importing all of
them into Zotero. Keep search scope, provider, query, retrieval time, selection
decisions and coverage. Selected literature and PDFs belong exclusively to
Zotero; unselected candidates are bounded research results, not another editable
catalog. Define retention with the first discovery integration.

## 2. One database, explicit schemas

Markdown is suitable for prose and derived exports. It is not the authority for
entry metadata, evidence categories, source locators or graph relationships.
Those belong to typed database records with explicit integrity rules.

Reuse PostgreSQL, stable IDs, immutable revisions and existing domain types.
Distinguish the logical schema from its physical tables: this specification does
not require a new table for every row below or a replacement of the ledger.

| Logical record | Required structured content |
| --- | --- |
| Research question | Question, purpose, work context and lifecycle |
| Research association | Question, entry, role, rationale and attribution |
| Source reference | Zotero identity and verified document-version references |
| Extraction snapshot | Ordered blocks, locators and extraction issues |
| Claim | Proposition, structured scope and qualifications |
| Evidence relation | Claim revision, source passage, finding and appraisal |
| Assessment | Complete evaluated evidence set, balance, confidence and limits |
| Note | Kind, title, prose and structured citations to knowledge revisions |
| Review | Target/dependency revisions, decision, author and rationale |
| Document citation | Citing location, reference entry and resolved target |

### Common metadata

Retain stable ID, revision, record kind, creation timestamp and attributed
actor.
Specify the contract version independently of content revision. Record origin
as manual, imported or model-assisted without equating model assistance with
the author's authorship. Link generated revisions to their processing run and
pinned
inputs, model configuration, prompt version and author-rule version when used.
Run details need not be copied into every entry.

Keep review state derived from attributed decisions and dependency freshness;
do not add an independently editable approval flag. Processing success, reading
status, scientific assessment and permission to publish are distinct dimensions.

Use type-specific fields rather than a universal metadata bag. Represent unknown
and not-applicable scope values explicitly. Do not fill missing information by
guessing. Introduce controlled vocabularies only for fields used by current
validation or retrieval; no universal ontology or person/institution catalog.

### Storage and validation

- Declare a strict Pydantic schema for each actual operation and record type.
  JSONB alone does not enforce that schema.
- Use relational columns, foreign keys, uniqueness and checks for identities
  and relationships that require database integrity or indexed traversal.
- Retain the existing immutable revision payloads where they fit. Any relational
  projection of those payloads must be derived and updated transactionally, not
  a second writable representation of the same claim or evidence relation.
- A new relation with no existing owner needs one canonical write path. Validate
  allowed endpoint types, revision pins and relation semantics there.
- Keep Markdown, HTML, graph exports and supporting/opposing source lists as
  derived views. Do not maintain their contents independently.

Choose the smallest physical migration after inspecting actual queries and
consumers. No general entity-attribute-value system or universal command bus.

## 3. General claims, precise evidence

A claim should express a useful proposition above the level of an individual
paper when the evidence permits it. It remains a claim, not an established fact.
Preserve its population, conditions/intervention, comparator, outcome and time
horizon as explicit scope fields where applicable, with qualifications in prose.

For example, "AI support during learning can impair later unaided test
performance" is a candidate formulation, not an endorsed empirical conclusion.
It distinguishes learning with assistance from taking a test with assistance.
"AI worsens student test results" hides that distinction and is too ambiguous
to classify evidence consistently.

Keep experiment-specific findings in evidence records: observed result,
population, conditions, measured outcome, time horizon, methodological limits
and exact passage. Reuse study/dataset identifiers where established; unknown
overlap stays unknown. A reference to the same study does not add independent
replication. Do not introduce a separate study catalog until shared study
identity has a concrete use that cannot be met by the existing grouping.

One source may contribute several findings. A general claim may receive many
evidence relations. Never force every finding into an existing broad claim or
suppress a genuinely independent proposition to reduce record count. Changing
the meaning or materially broadening the scope requires a new claim; historical
experiment-specific claims remain valid rather than being silently generalized.

Each evidence relation must identify:

- The claim revision and exact source/extraction revision and locator.
- The verbatim passage and a separately labelled formulation of the finding.
- Supports, contradicts, qualifies or unclear, with a brief rationale.
- Directness, relevant study conditions, methodology and limitations.
- Attribution and review provenance; secondary reporting must remain explicit.

The same passage may bear differently on different claims. Record and justify
each relation. A shared topic, changed population or immediate-versus-delayed
outcome is not automatically contradiction. Numerical agreement between tools
does not establish correct interpretation.

### Uniform claim presentation

Render every claim with a concise statement, scope and current assessment.
Then show supporting, contradicting, and qualifying/unclear evidence as bullets,
each with an inline source citation and inspectable locator. Keep qualifying and
unclear relation types distinguishable even when displayed together.

Generate these groups from evidence relations. Empty groups mean no such
evidence is recorded within the stated coverage, not that none exists. The
assessment explains synthesis and uncertainty; relation counts do not determine
the verdict. A portable Markdown export uses the same data and structure.

## 4. Knowledge graphs and citation networks

Two different kinds of edges are required:

| Network | Examples |
| --- | --- |
| Knowledge | Evidence supports claim; note uses claim; entry addresses topic |
| Citation | Document cites another work at a particular source location |

Derive knowledge edges already represented by evidence and note citations.
Do not copy them into a separately maintained generic edges table. New semantic
links need named meanings, provenance and applicable review rules, not only a
similarity score. Expose graph views with an explicit current or historical
revision policy so re-extraction does not silently change an earlier analysis.

For document citations, preserve the reference-list wording, extraction locator,
reliably resolved in-text markers, external identifiers and resolution outcome.
A target may be an external work not held in Zotero. Its verified identifier is
enough to participate in a bounded network; no automatic literature import is
required. Keep ambiguous references unresolved. Different document versions are
not automatically the same work merely because titles resemble each other.

When a work is selected later, connect the resolved identifier to its Zotero
identity instead of creating a duplicate node or second editable bibliography.
Keep external search metadata only as attributed retrieval observations where
needed for reproducibility. Current editable literature remains Zotero-owned.

Separate citations observed in a PDF from edges reported by an external
provider. Preserve method/provider, observation time, resolution evidence and
coverage; multiple observations of an edge are not multiple citations. Network
analysis must state selection boundaries, unresolved matches and temporal scope.
Missing edges in a partial dataset do not prove absence of citation. Citation
counts, centrality and similarity never become evidence-strength scores.

Reuse external discovery tools named by the user, such as OpenAlex, OpenScholar
and Google Scholar, where an appropriate supported integration is verified.
No particular API, automated-access method or provider deployment is assumed
here. Inspect current official documentation and existing adapters before
selecting one. Do not recreate a general scholarly search engine locally.

## 5. Embeddings and retrieval

Embeddings are rebuildable search indexes, not canonical knowledge. Each vector
must identify its entry/block, content revision, chosen input fields, text hash,
model version and configuration. Define chunk boundaries and language treatment
with the selected embedding integration. Do not mix incompatible vector spaces.

Candidate inputs are claims with scope, source sections with heading context,
and Zettel with titles. Avoid indiscriminately embedding entire JSON records,
technical logs or every field. A content change invalidates the affected current
index; it does not rewrite the historical source or quotation.

Start with existing full-text and explicit-reference retrieval. Add embeddings
in PostgreSQL only after selecting and testing a provider/model against real
queries. Combine candidates by stable identity and supply their exact revisions
and coverage to matching. Similarity proposes candidates; it cannot decide
equivalence, contradiction, relevance to every project or scientific truth.

No separate vector database, graph database or graph-maintenance service is
required now. Add infrastructure only for an observed limitation of the existing
database, with a reproducible retrieval or analysis test.

## 6. Writing responsibilities and author rules

| Text | Purpose and constraints |
| --- | --- |
| Source overview | Optional summary of question, method, findings and limits |
| Claim/evidence | Concise propositions and precise, cited findings |
| Assessment | Explain the combined evidence and its coverage limits |
| Zettel | One coherent, reusable thought or argument in the author's language |
| Wiki article | Synthesize a subject and connect relevant Zettel and evidence |
| Change rationale | Explain the benefit of an edit and show its diff |

Original abstracts and source passages remain source content. An optional source
overview uses the existing source-note kind and must cite its factual
statements.
It is not a second summary entity. A Zettel may contain a strong thesis, but
must
distinguish observed findings, the author's interpretation and further
hypotheses.
Model-created proposals do not automatically become the author's authored
thoughts.

Develop separate authoring rules for the text types rather than using one
undifferentiated synthesis prompt. Preserve exact quantities, qualifications and
attribution. Improve existing prose selectively; do not equate more caution,
more words or more citations with better writing.

Choose citations for direct relevance to the statement, source fidelity,
methodological usefulness and informative counterevidence. Prefer the original
work for a primary finding when actually inspected. Reviews can support their
own synthesis; they are not independent replications of included studies.
Never imply reading an original that was only encountered through a citation.
Every factual addition needs support, but an essay need not reproduce the full
evidence register. Keep the broader basis accessible through structured links.

### Small authoring test center

Use existing prompts, run logs, revision comparisons and the review interface.
Start with a bounded set of author-selected writing samples and real tasks, not
a new evaluation platform. Personal samples and outputs remain private runtime
artifacts; versioned software documentation must not contain them by default.

1. Select representative writing samples and agree what should be preserved.
2. Derive a short, versioned author-rule set covering argument structure,
   vocabulary, sentence style, useful compression and unwanted formulations.
3. Prepare fixed source packets and expected evidence, including a genuinely
   relevant new-source-to-note contribution and a correct no-change case.
4. Compare prompt/model variants on the same inputs, preferably with model
   names hidden during the author's evaluation. Preserve outputs and revisions.
5. Record concrete corrections and preferences; accept rule changes explicitly.
6. Repeat a small held-out set to detect regressions rather than only improving
   the examples used to write the rules.

Evaluate source fidelity, numerical/scope precision, citation relevance,
argument quality, useful synthesis and author-style fit separately. Establish
acceptance criteria with reviewed examples; no invented global quality score.
Fluent prose cannot compensate for a material factual error.

Luna may draft bounded proposals. A larger configured model may check selected
outputs against the supplied evidence and author rules. Specify escalation
conditions and resource limits during the experiment; this decision does not
select or deploy a model. Deterministic checks validate reference existence,
revision pins, exact quotes and structured values where comparable. Semantic
checks must inspect source context and report concrete issues; exact numeric
matching alone cannot detect reversed groups or changed causal meaning.

A second model remains fallible and cannot grant human approval. Preserve its
issues, disagreements and attribution instead of silently repairing the text.
Human-authored or approved entries require a proposed diff and human decision.
Ordinary reads trigger neither generation nor automated rewrites.

## 7. Incremental implementation plan

These steps extend the ongoing extraction/source-view work; they do not restart
it or authorize rewriting historical records to fit a new conceptual model.

1. Inventory existing schemas and queries. Specify concrete contracts for
   research associations, structured claim scope, evidence and citation
   resolution. Map common metadata to existing revisions/runs before adding
   fields. Record canonical versus derived ownership and migration rules.
2. Build one bounded case: a research question, selected sources, a general
   claim with differently classified evidence, and two or three useful Zettel.
   Use actual evidence; never manufacture contradiction for test completeness.
3. Add structured storage and uniform claim views through existing commands.
   Preserve legacy text and revision readers for real historical citations.
   Migrate only after checking identifiers, quotes, locators and review
   behavior.
4. Run the author-rule experiment on that same case. Compare Luna drafts and
   selected larger-model checks. Include known failures: lost quantities,
   unsupported causal wording, topic-only matches and redundant caveats.
5. Implement bounded discovery and citation resolution for a real landscape
   question. Verify external targets without Zotero import, ambiguity handling,
   later Zotero selection, edge deduplication and reproducible graph scope.
6. Evaluate lexical retrieval first, then embeddings if needed. Measure useful
   new contributions and false matches, not merely more links or sources.

Required acceptance includes valid database references, idempotent retries,
stable historical citations, no duplicate writable structures, explicit unknowns
and clear separation of reading, processing and review states. A broader claim
must not hide incompatible study conditions. A graph must retain its edge
provenance. Regenerating indexes or exports must not create knowledge revisions.

Keep deployed status, pending contracts and observed quality results separate.
Do not claim this workflow solved the negative consolidation result until a
reviewed test demonstrates meaningful incorporation of relevant new evidence.
