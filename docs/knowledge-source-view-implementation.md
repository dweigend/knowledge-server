# Source view implementation record

Started 2026-09-15. Implementation in progress; acceptance is not yet complete.
This record predates the standalone repository. The separate OCR benchmark
environments were removed before this work began. It is historical context,
not evidence that the current extraction acceptance is complete.

## Reuse, replace and remove

- **Reuse:** Zotero adapter and verified attachment hashes. Sole PDF and
  metadata authority.
- **Reuse:** Revision ledger, receipts and exact quotes. Preserve existing
  citations.
- **Reuse:** PDF.js and pinned PDF endpoints. Working embedded PDF navigation.
- **Reuse:** Existing notes and evidence relationships. No second summary or
  knowledge store.
- **Replace:** Source branch of generic detail template. Compose an article
  from its owners.
- **Replace:** Flat extraction for new processing. Preserve structure and
  locations.
- **Remove:** Superseded source template branch. One source presentation path.
- **Retain read-only:** Existing source page snapshots. Existing evidence cites
  this exact text.
- **Retain read-only:** Pre-Zotero source decoder. Historical revisions still
  use that shape.
- **Avoid:** Separate Markdown, HTML or PDF archive. Derive views from one
  snapshot and Zotero.

The first vertical slice uses a pinned existing source. Corpus migration follows
visual comparison of that slice and representative table/figure fixtures.
Processing creates extraction snapshots, not replacement knowledge revisions.
No existing source, evidence or review is rewritten during this transition.
