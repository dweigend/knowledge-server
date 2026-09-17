# Source article view: binding specification

Decision date: 2026-09-15. Status: approved requirements; implementation and
acceptance incomplete.
This document specifies the next source-view revision. It does not claim that
extraction quality, metadata completeness or the new interface are deployed.

This is the authoritative specification for source presentation and its minimal
architecture. It supersedes conflicting source-view proposals in the concept,
MVP and module roadmap. Existing citation integrity and review rules in the
[contracts](knowledge-contracts.md) remain binding.

The [document extraction module](knowledge-extraction.md) specifies the approved
Docling/Marker workflow, discrepancy checks and background jobs. It implements
the extraction responsibility below using this same snapshot contract; it does
not introduce a second source-view model. See the [implementation status](README.md#implementation-status).

The [modular workflow](knowledge-plugin-architecture.md) adds an independent
link/PDF inbox alongside existing Zotero intake. Temporary preparation may
precede Zotero import. This source view describes accepted sources after their
Zotero identity is verified; it does not require the inbox itself to be Zotero.
Its extraction and presentation boundaries remain unchanged.

## Purpose

Opening a source must explain what the document is, who wrote it, how it is
structured and what it contains. The supplied Nature screenshots establish the
information hierarchy: article header, sections, figures and references. The
Scholar screenshot establishes a separate, concise analytical overview.
These are information-design references, not requirements to copy their styling,
external services, citation metrics or access controls.

The first implementation uses the existing Python application and plain HTML.
The existing PDF.js viewer remains the PDF reader. A future dashboard consumes
the same source information without taking ownership of domain behavior.

## Required reading experience

The article title is the main heading. Internal record kinds, actor strings and
migration identifiers must not occupy the article header.

| Area | Required contents |
| --- | --- |
| Article header | Title, authors, year, venue and document version |
| Citation | Readable citation, DOI/publisher, copy citation, BibTeX |
| Source actions | Read PDF and open the corresponding Zotero item |
| Overview | Original abstract and separately labelled generated overview |
| Authors | Authors mapped to the affiliations reported in this document |
| Sections | Hierarchical outline linking to extracted text and PDF locations |
| Figures and tables | Original number, caption, preview and source location |
| References | The document's bibliography with links where resolved |
| Related knowledge | Existing claims, assessments, Zettel and wiki articles |
| Technical details | Collapsed extraction, revision and processing details |

Original content and generated interpretation must be visually distinguishable
through headings and labels, including in unstyled HTML. Navigation must work
with ordinary links. The PDF reader must retain a return link to the source
view.

### Citation and authors

- Bibliographic display and BibTeX must use the Zotero integration. The model
  must not invent missing citation fields or produce an independent BibTeX copy.
- A working paper remains that working paper. Metadata for a later publication
  must not silently relabel the attached document. A mismatch needs review.
- Affiliations describe authorship at publication, not current employment.
  Preserve the document's author-to-institution mapping and its source location.
- Link institutions and author identifiers only when their targets are verified.
  An unresolved name remains plain text; it must not become a guessed link.
- Unknown metadata is explicitly unavailable. A failed Zotero request must be
  distinguishable from a field that Zotero does not contain.

### Abstract and analytical overview

Show the original abstract as source content. A generated overview is optional
and separately labelled. It covers research question, method, main findings and
limitations, with inspectable source locations for its factual statements.
It describes this document; cross-source confidence belongs to the existing
claim and assessment system.

The [Zotero ownership decision](knowledge-zotero-ownership.md) places the original
abstract on the Zotero item and a generated overview in a separate Zotero child
note. Read both through the existing adapter. Migrate eligible database source
notes after verifying content and pinned references; retain cited historical
revisions without maintaining two editable summaries. A missing overview must
not block reading the source, and an import need not create one automatically.

Page reads and PDF navigation must not invoke Hermes or a model. Generation is
an explicit processing operation; its result retains model and input provenance.
A conversational assistant is outside this first revision.

### Sections, figures and tables

Preserve heading hierarchy and reading order. Render extracted text as formatted
Markdown/HTML, with links back to the exact original PDF location. Sanitize
rendered document content; documents are untrusted input.

Figure previews show original PDF content, not model-redrawn replacements.
Preserve captions and figure numbers. Previews may be rendered from a pinned PDF
region; regenerable previews are technical artifacts, not library assets.

Tables must preserve headers, row/column relationships, units and footnotes.
Simple tables may use Markdown. Merged cells or other structures that Markdown
cannot represent faithfully use HTML tables and an original preview. Never
flatten a complex table into misleading prose or silently lose its structure.

### References

Show the reference list as it appears in this document. Link citation markers
in the extracted text to their reference entries where reliably resolved.
Attach verified DOI/publisher links and matches to existing Zotero items.
Ambiguous matches stay unresolved. A reference list entry does not automatically
create a Zotero item, a knowledge source, a claim or a citation-network node.

### Relevant limitations and technical details

Keep document version, substantive discrepancies and incomplete extraction
visible beside the affected content. For example, an unreadable table must not
appear to be a document with no tables. Distinguish absent, unprocessed, partial
and failed extraction where that distinction affects reading.

Move actor IDs, hashes, raw extraction, migration identifiers and processing
logs behind technical details. Explain page mapping at the point of navigation;
users must not calculate cleaned-PDF page offsets themselves.

## Minimal architecture and ownership

Use four responsibilities within the existing application. These are boundaries,
not four new services, frameworks or mandatory packages.

| Owner | Authority | Must not become |
| --- | --- | --- |
| Zotero | Bibliography, PDFs, citation export | Second catalog/archive |
| Extraction | Versioned content and locations | Literature/author management |
| Knowledge | Claims, evidence, notes, assessments | Display metadata copy |
| Web adapter | Compose and render read results | Persisted duplicate article |

The source view is a read composition, not another database entity. Reuse the
existing Zotero adapter, source identities, revision ledger, note operations and
PDF reader. Extend only the concrete extraction and presentation capabilities
needed by this specification. Keep business rules outside templates and routes.

Do not introduce generic provider registries, a shared service framework, a new
retrieval layer, event bus, vector database or person/institution catalog for
this view. The broader module roadmap is not an implementation checklist.

## Document extraction contract

One versioned extraction snapshot is the authority for document-derived content.
The [extraction workflow](knowledge-extraction.md#one-snapshot-contract) adds
per-block method attribution, candidate discrepancies and job provenance.
Its minimum information is:

- Identity: pinned knowledge source revision, Zotero attachment identity,
  original PDF hash, extraction method/version and processing outcome.
- Ordered blocks: stable identifiers within that snapshot, block type, content,
  heading level where applicable, and original PDF locations.
- Locations: one-based original PDF page and, for previews, page region with
  an explicit coordinate convention. Cleaned PDF navigation uses a stored map.
- Figures and tables: original labels, captions, locations and faithful content
  or preview regions. Keep table structure rather than only a text rendering.
- Document relationships: citation markers to reference entries and authors
  to the document's affiliation statements, each with source locations.
- Quality: unresolved relationships and partial/failed extraction attached to
  the affected blocks; do not use one unexplained overall quality score.

Markdown and HTML are renderings of this structure, not independently maintained
copies. BibTeX and editable publication metadata remain Zotero-owned. Extracted
affiliation statements and bibliography passages are source evidence, not
editable catalogs. Bibliographic corrections are maintained through Zotero.

Snapshots are justified by exact quotations and reproducible navigation. They
are immutable and require no second manual maintenance. Re-extraction creates
a new snapshot; it must not rewrite locations used by historical evidence.
Block identifiers need not remain identical across different snapshots.

Existing citations must continue to resolve against their original source
revision and text. Never fabricate historical metadata that was not retained.
Distinguish a citation exported from current Zotero metadata from the historical
document version. Existing historical metadata snapshots remain read-only.
Preserve cited historical PDF versions in Zotero. A changed attachment hash must
not serve as the old version.

## Replacement rules: no inherited duplicate structures

| Existing pattern | Required treatment |
| --- | --- |
| Generic record dump as source page | Replace with the article composition |
| Prominent technical warnings | Relocate; keep substantive limits visible |
| Flat page extraction | Replace for new extraction; retain history |
| Editable metadata or PDF copies | Remove after verified Zotero ownership |
| Automatic per-source notes | Do not restore; overviews remain optional |
| Markdown and HTML stores | Derive both from one extraction snapshot |
| Old source notes reused without checking | Validate or mark for review |
| Duplicate parser or rendering paths | Remove superseded paths at cutover |
| Old record formats | Decode only where existing history requires them |

No compatibility wrapper is justified solely because old code exists. A retained
legacy path must identify the records or citation behavior that still need it.
Keep that path read-only where possible and state its removal condition.
Do not carry obsolete abstractions or fields into the new write contract.

Preserve real transaction boundaries, exact-quote validation, request receipts
and revision checks. Simplicity must not erase these integrity guarantees.
Use short Python functions with one concrete task, explicit names, early returns
and concise public docstrings. Avoid forwarding-only helper layers.

## Implementation sequence and migration

1. Inventory the current source routes, templates, extraction outputs and
   historical citation formats. Record which parts are reused or replaced.
2. Implement one representative article through the existing application.
   Include affiliations, references, a figure and a nontrivial table in the
   acceptance fixture set if one article does not contain them all.
3. Verify the structure and article view against the original PDFs before
   processing the remaining corpus. An OCR benchmark alone is not acceptance.
4. Produce new snapshots without overwriting existing evidence or reviews.
   Compare source identities, revision counts and citation targets before and
   after migration. Inspect every migrated test source's quotation resolution.
5. Cut over the source view and remove superseded routes, templates and write
   paths in the same delivery. Keep only documented historical readers.
6. Delete redundant PDF copies only after hash-verified Zotero retrieval and
   successful citation/PDF navigation checks. Retain necessary immutable
   history.

No new schema, dependency or migration is approved merely by naming it here.
Select the smallest concrete implementation after inspecting current code.
Document any unavoidable extraction limitation rather than manufacturing data.

## Acceptance criteria

The source-view revision is complete only when these checks pass:

- Header and BibTeX agree with the corresponding Zotero item; unavailable fields
  and service failures are represented honestly. Document versions are explicit.
- Author-affiliation mappings match the source, including multiple affiliations.
- Section links reach the correct text and original/cleaned PDF pages.
- Figures retain their numbers and captions; tables retain headers, merged
  relationships, units and footnotes against visual inspection of the original.
- Reference entries and text markers resolve correctly; uncertain matches are
  shown as unresolved without adding duplicate Zotero items.
- Original abstract, generated overview and existing knowledge are distinct.
  Each generated factual statement has an inspectable source location.
- Incomplete extraction is visible; technical logs do not dominate reading.
- Loading or navigating a source makes no model request and writes no knowledge
  records. Repeated processing does not create duplicate library entries.
- Historical quotations and source revisions remain readable after metadata
  edits and re-extraction. Missing historical PDFs are reported explicitly.
- Browser inspection verifies the article and PDF navigation in the embedded
  browser. HTTP success alone is insufficient.
- Relevant repository lint, type and integrity tests pass. Documentation records
  remaining limitations and the legacy readers that still have a concrete use.

Use the fixture checks to evaluate extraction tools separately from generated
overview quality. Neither a model's self-rating nor valid JSON establishes that
tables, references or scientific claims were extracted correctly.
