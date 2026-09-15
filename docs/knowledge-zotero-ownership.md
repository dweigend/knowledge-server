# Zotero ownership and data-model principles

Decision date: 2026-09-15. Status: approved target, migration pending.
Use Zotero extensively as the literature workspace and as a reference model
for clear data structure. This decision changes documentation only; it does
not claim that metadata, notes, annotations or tags have been migrated.

This document owns literature responsibilities and supersedes earlier proposals
to maintain editable paper summaries in the knowledge database. The
[source-view contract](knowledge-source-view.md) still owns presentation, and
the [extraction contract](knowledge-extraction.md) owns technical derivations.

## Zotero as a reference model

Adopt Zotero's useful structural principles rather than copying its internal
database or building a second literature manager:

- Use explicit object types with appropriate fields: a book chapter, report
  and journal article have different metadata requirements.
- Separate the literature item from its attachments, child notes and PDF
  annotations. Preserve the parent relationship and each object's identity.
- Model creators with roles and distinguish people from organizations.
  Do not flatten authors and editors into an ambiguous display string.
- Use collections for grouping and tags for reusable descriptors. Membership
  in several collections must not duplicate the underlying item.
- Keep identity, relationships and content separate. Use stable references,
  not titles, filenames or technical tags as identifiers.
- Derive citations and presentation from structured records. Never make a
  formatted citation, Markdown export or HTML view a second editable authority.
- Use explicit versions and conflict checks when editing shared objects.

Apply the same clarity to claims, evidence, assessments and notes in our own
system. Do not introduce a universal item framework or copy Zotero's schema:
each domain retains only the types and relationships it actually needs.

## Canonical ownership

| Information | Owner and representation |
| --- | --- |
| Bibliographic metadata and original abstract | Zotero literature item |
| Original and required historical/clean PDFs | Zotero child attachments |
| Personal highlights and PDF comments | Zotero annotations on the attachment |
| Paper summaries and reading notes | Zotero child notes |
| Topics, reading status and grouping | Zotero tags and collections |
| OCR, tables, page maps and issues | Knowledge extraction snapshots |
| Claims, evidence relationships and assessments | Knowledge database |
| Cross-source permanent notes and wiki articles | Knowledge database |
| Import receipts, hashes, jobs and mappings | Application technical tables |

The web adapter composes these owners through the existing Zotero integration.
It must not maintain parallel editable abstracts, summaries, tags or comments.
An extracted abstract remains permissible as immutable source evidence with its
PDF location; its wording is not another metadata field to maintain manually.
Affiliations without suitable native Zotero fields remain located source
content. Do not invent metadata fields or overload unrelated fields.

## Metadata and paper summaries

Use the correct Zotero item type and its supported fields. Verify metadata
against the attached version and suitable publisher/identifier records. Populate
applicable fields, not every possible field. Unknown values remain unknown;
a preprint must not silently acquire a later publication's identity.

The Abstract field holds the original abstract. Store a generated summary as a
separate, clearly labelled child note with source locations and generation
attribution. It may cover question, method, findings and limitations. Personal
notes remain distinct, and regeneration must not overwrite human edits.

Use the Zotero note key to identify an existing summary; do not create one note
per processing run. The knowledge database keeps references and only the
immutable provenance needed for review or citations. It does not keep a second
editable summary. Existing source notes require verified migration before their
old write path is retired; historical revisions remain readable.

## Annotations and relationships

Zotero stores its own PDF annotations separately from the PDF bytes. Serving
the attachment alone therefore does not display those annotations. Use Zotero
as their owner and read them through the supported integration, or open the
Zotero reader. Do not build another annotation editor or synchronize two
editable
comment stores. Verify supported annotation operations and coordinate semantics
against the installed version before implementation.

An annotation can seed an evidence proposal; it is not automatically an accepted
claim or assessment. Accepted evidence retains the exact quote, attachment/hash,
page or region, and relevant immutable snapshot even if the annotation changes.

Use Zotero's related items for literature relationships such as chapter/book
or alternate versions. These symmetric links do not replace directed citation
relationships or the knowledge system's supports/contradicts relations. A PDF
reader's reference popup is not proof of a resolved library item or citation
edge.

## Tags and collections

Use a small controlled vocabulary with one canonical spelling per concept.
Start with a few useful topics and add method descriptors only when helpful.
Keep personal reading status separate from automated processing status.

- Topic examples: `Künstliche Intelligenz`, `Selbstreguliertes Lernen`,
`Feedback`.
- Method examples: `Randomisierte Studie`, `Systematischer Review`.
- Personal status examples: `Zu lesen`, `Gelesen`.
- Use collections for projects or research questions; store contextual relevance
  explanations in the knowledge workflow rather than encoding them in tags.

Hermes selects existing vocabulary terms; new terms are proposals. Preserve
user-managed tags when updating an item. No hashes, batch IDs or request IDs
belong in the user-facing tag vocabulary. A vocabulary definition is a naming
rule, not a duplicate database of Zotero tag assignments.

## Integration and historical integrity

Extend the existing Python Zotero adapter. Zotero 10 supports authorized local
API writes as well as reads; local and web API credentials and object versions
are distinct. Use the local server identity, library and item keys consistently.
Use documented item templates, targeted updates and version preconditions.
Array updates must preserve unrelated tags, creators and collection memberships.
Do not access or mutate Zotero's SQLite tables directly.

Zotero object versions support change detection; they do not replace our
immutable citation history. Keep cited PDF versions as Zotero attachments and
retain exact evidence snapshots. Any technical cache must be disposable,
version-aware and require no separate manual maintenance.

## Observed gap and smallest migration

The inspected importer sends only title, creators, year, DOI and URL through
generic RIS. It omits richer item-type metadata and uses `knowledge-pilot:…`
and `knowledge-pilot-sha256:…` tags for import reconciliation and upload
recovery.
Removing those tags before replacing that dependency can cause duplicate
imports.

1. Fully curate one representative existing item: type, verified metadata,
   original abstract, grounded summary note and controlled tags.
2. Read that item, note and annotations in the source view through Zotero.
   Verify links, manual-edit preservation and existing citation resolution.
3. Replace technical tag identity with durable import-to-Zotero mappings and
   verify duplicate prevention and interrupted-upload recovery.
4. Migrate remaining summaries and metadata with explicit conflict handling.
   Remove technical tags and superseded copies only after verified transfer.

## Official references

- [Item types and fields](https://www.zotero.org/support/kb/item_types_and_fields)
- [Metadata import](https://www.zotero.org/support/adding_items_to_zotero)
- [Notes](https://www.zotero.org/support/notes)
- [PDF reader](https://www.zotero.org/support/pdf_reader)
- [Annotation storage](https://www.zotero.org/support/kb/annotations_in_database)
- [Collections and tags](https://www.zotero.org/support/collections_and_tags)
- [Related items](https://www.zotero.org/support/related)
- [Local API](https://www.zotero.org/support/dev/web_api/v3/local_api)
- [API reads and exports](https://www.zotero.org/support/dev/web_api/v3/basics)
- [Version-checked writes](https://www.zotero.org/support/dev/web_api/v3/write_requests)
