# Document extraction module

Decision date: 2026-09-15. Status: approved workflow; implementation in
progress,
acceptance pending. See the [implementation status](README.md#implementation-status).
This document specifies extraction within the existing Python application.
It extends the [source-view contract](knowledge-source-view.md), which remains
authoritative for presentation and snapshot structure. This is not a deployed
independent application or a second document store.

## Purpose and ownership

Produce source-faithful, versioned document content for reading and downstream
knowledge operations. Extraction quality and scientific evidence strength are
separate judgments. Agreement between extractors does not establish truth or
guarantee a correct transcription.

| Responsibility | Owner |
| --- | --- |
| Literature metadata, original and historical PDFs | Existing Zotero adapter |
| Ordered document blocks, locations and extraction checks | Extraction module |
| Claims, evidence, assessments and notes | Existing knowledge modules |
| Optional interpretation and knowledge proposals | Hermes with Luna |
| Article composition and sanitized rendering | Existing web adapter |

Reuse source identities, revision storage, PDF page maps and exact-quote checks.
The module cannot create literature entries, accept claims or edit notes as an
extraction side effect. It does not own a model planning loop.

## Processing workflow

```text
Pinned Zotero PDF
  → Docling: complete document structure
  → Marker: second reading of table, scan and suspect pages
  → compare candidates and record extraction issues
  → one versioned extraction snapshot
  → derived Markdown/HTML and bounded knowledge inputs
```

1. Resolve the requested source revision through Zotero and verify its PDF hash.
   Process temporary files; preserve original page numbers and the existing
   cleaned-PDF mapping. Never substitute a changed attachment for a pinned PDF.
2. Run Docling over the complete document. Consume its structured output,
   including table cells and footnotes, rather than treating its default
   Markdown export as the authoritative extraction.
3. Run Marker on every detected table page and every page without a usable text
   layer. Include pages with empty or visibly malformed extraction. Table pages
   receive a visual reading, not just a second use of the same PDF text layer.
   Record why each page received a second reading. Table detection itself is
   fallible; representative visual checks remain necessary.
4. Compare page coverage, table dimensions, header/value alignment, units and
   footnote references against their texts. Compare corresponding cells rather
   than unordered sets of numbers. Normalize whitespace for comparison only;
   preserve source wording and superscripts in the stored result.
5. Use Docling as the initial candidate for digital text and document structure;
   use Marker's visual candidate for scanned content and re-read tables.
   This is a default selection rule, not a quality guarantee. Record the
   selected
   method per block. Unresolved discrepancies remain visible in the snapshot.
6. Persist the snapshot and its check results atomically. Render Markdown/HTML
   from that snapshot. Send only eligible passages to the existing knowledge
   workflow; completion of extraction does not imply scientific acceptance.

Marker supports page selection and forced OCR. Whether forced OCR reproduces
the successful raster-table test is an implementation acceptance check. Do not
silently equate an untested configuration with the benchmark result.

## Checks and unresolved content

Use explicit block-level issues, not a synthetic overall percentage. A job may
succeed while its document still contains content requiring review.

- Conflicting numbers, shifted headers, missing footnotes or missing content
  mark the affected block as requiring review. Failed processing is distinct
  from a source that genuinely contains no such content.
- An automatic check passing means only that the recorded checks passed.
  It is not a human review or an assurance that both tools cannot share an
error.
- Unresolved blocks remain readable beside their pinned PDF preview, but cannot
  supply newly accepted evidence automatically. Human resolution records the
  selected or corrected content and its attribution as a new snapshot revision.
- Luna may propose a resolution or a diagram transcription. Preserve it as a
  labelled proposal with its input provenance; do not silently rewrite source
  text, numbers or footnotes. Diagram values need verification against the PDF
  before becoming eligible evidence.
- Multi-page tables retain page locations and continuation information. Do not
  guess a cross-page join; an unresolved continuation needs review.

## One snapshot contract

Extend the [existing extraction contract](knowledge-source-view.md#document-extraction-contract)
instead of introducing independent Docling and Marker document entities.
The concrete Python schema is defined during implementation after code
inspection.
In addition to the source-view fields, retain:

- Extraction identity and revision, pinned source/attachment and PDF hash.
- Tool versions, configuration fingerprint and selected method for each block.
- Page coverage, second-reading reasons and checks with concrete issue
locations.
- Review attribution and candidate content needed to explain unresolved or
  resolved differences. Candidate output is technical provenance, not a second
  editable source or another searchable knowledge corpus.

One active snapshot is selected for a source version. Historical snapshots stay
immutable wherever quotations or review decisions depend on them. New evidence
pins the extraction revision and block/location in addition to its source.
Legacy citations continue to resolve against their original text and page map.
Re-extraction never changes the text behind an existing quote.

Do not maintain Markdown, HTML and a flat page-text copy independently. Generate
views and model packets from the common structure. Retain old flat snapshots
only for identified historical readers. Temporary PDFs and page images are
deleted after processing. Historical PDFs remain Zotero attachments.

## Background execution

Use one Python worker started by systemd and a small extraction-job table in the
existing PostgreSQL database. This executes fixed processing steps; Hermes still
owns agent interaction. No Redis, Celery, event bus or generic workflow engine.

- Start with one expensive OCR job at a time. Favor completion and predictable
  memory use over throughput; the server can process work around the clock.
- Identify work by pinned PDF/source version, tool versions and configuration.
  Repeating that request reuses its job/result rather than creating duplicates.
- Keep job states simple: queued, running, succeeded and failed. Content review
  status belongs to the snapshot, not the execution state.
- Claim and finish jobs in short transactions. Never hold the existing global
  database lock during OCR, subprocess execution or Zotero network access.
- Recover interrupted running jobs on worker restart. Bound retries of transient
  failures; persistent errors remain failed with a readable reason. Retrying
  does not overwrite an earlier successful snapshot.
- Log step, tool/configuration, page range, duration, outcome and error
privately.
  Terminate owned helper processes on failure or shutdown and remove staging
  files. Do not allow tool runtime files or servers to escape configured ownership.

## Module boundary and operations

The module is a capability inside the existing Python application. A separate
worker process isolates expensive processing; it does not introduce a second
application API or database. Web requests read completed snapshots and never
start OCR or call Hermes implicitly.

| Operation | Input | Result and responsibility |
| --- | --- | --- |
| Request extraction | Source/configuration | Reusable job identity |
| Read job | Job identity | State and failure reason |
| Read snapshot | Source/extraction revision | Content and issues |
| Record annotation | Expected revision, changes, actor | New revision |

Source inputs are pinned revisions. Snapshot reads may omit the extraction
revision to select the latest result. Annotation writes require the expected
revision and reject stale input.

The worker owns tool execution and cleanup. Deterministic checks own candidate
comparison. Persistence owns job transitions and snapshot revisions. The web
adapter owns presentation; knowledge modules own evidence eligibility and
scientific assessment. Keep those responsibilities separate without adding
forwarding-only classes or a generic plugin framework.

For the first rollout, extraction accepts existing Zotero sources. The
[independent inbox](knowledge-plugin-architecture.md#2-two-entry-paths-one-processing-workflow)
is a later integration seam: temporary intake identity must be bound to Zotero
before canonical knowledge acceptance. It is not another literature store.

Do not run PaddleOCR as a third default pass. Add another engine only if a
reproducible failure remains that Docling and Marker cannot handle. Likewise,
Luna is optional for interpretation proposals, not required to operate this
module. Background runtime alone is not a reason to add more processing stages.

## Minimal implementation and acceptance

Keep the public operations limited to requesting extraction and reading its
status/result. Internally separate tool adapters, deterministic checks, snapshot
persistence and job execution. Use existing modules where they fit; create no
generic provider registry or forwarding-only service classes. Follow the
[Python coding rules](../AGENTS.md).

1. Inspect and reuse current ingestion, source revision and page-mapping code.
   Implement the common snapshot and a Docling adapter, preserving all
   footnotes.
2. Add Marker's visual second reading and explicit discrepancy checks. Verify
   every value in a representative table with its headers, units and footnotes.
   Include page footnotes and test both digital and raster versions.
3. Verify two-column order, merged cells, multi-page tables and original diagram
   previews. Keep optional Luna diagram proposals separate from source content.
4. Exercise duplicate requests, interrupted jobs, bounded retries, cleanup and
   resource limits. Run repository checks and relevant integrity tests.
5. Integrate the source view and knowledge consumers. Re-extract test sources
   without overwriting citations; verify historical quotation/PDF resolution
   before changing the active snapshot or removing superseded write paths.

The four-page trial favored Docling for digital structure and Marker for the
raster table. Both lost content in some outputs; Luna changed source wording.
This supports the combination as a design hypothesis, not a corpus-wide quality
claim. Benchmark environments were deleted; implementation acceptance must use
explicitly pinned versions and fixtures. Documentation changes do not establish
that the running implementation has passed these acceptance checks.

## References

- [Docling document model](https://docling-project.github.io/docling/concepts/docling_document/)
- [Docling usage](https://docling-project.github.io/docling/usage/)
- [Marker options and Python integration](https://github.com/datalab-to/marker#usage)
