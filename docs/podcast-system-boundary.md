# Independent podcast system boundary

Updated: 2026-09-14. Status: proposed inter-system boundary, not an implemented
podcast service. This defines the research producer's content contract and the
independent consumer's ownership. Audio technology selection belongs to its
own project and is not a research-system decision.

## 1. Ownership

Research owns evidence, claims, scientific review and cited text publication.
It produces a released research document even when no podcast system exists.

The podcast system owns all media work:

- Transforming released text into essay-like narration in the chosen language.
- Narration revisions, pronunciation choices, spoken-source presentation and
  the amount of stylistic editing.
- Speech generation, voices, provider/runtime selection and audio revisions.
- Media jobs, queues, retries, cancellation, usage budgets and delivery.
- Its own deployment, credentials, permissions, storage, logs and recovery.

Keep this separate even when both systems run on the same Linux CPU-only host.
No research dependency requires a GPU or speech service. Independent processes
use separate workspaces and credentials; podcast state is not added to research
tables or the research Hermes session memory/scheduler configuration.

If the podcast project chooses Hermes for its own agent work, configure it as
an independently scoped runtime/profile with its own skills and state. Reusing
harness software does not place its workflow inside Research. The exact media
runtime, including whether an agent is needed, remains an independent decision.

## 2. Released-content contract

Research text publication emits an immutable `ResearchContentPackage` under
an explicit contract version. Proposed required fields:

- Package ID/revision, producer identity, contract/schema version and hash.
- Research document ID/revision and knowledge checkpoint.
- Cited Pandoc-Markdown text, language and paragraph-to-evidence references.
- Bibliography snapshot, citation-key/source mapping and used source versions.
- Review/release decision references, author attribution and release timestamp.
- Allowed scope, permitted use, rights limitations and content/file hashes.
- A manifest listing included files and explicitly omitted material.

This is a released-text package, not a dump of private chats or research tables.
Consumer access is limited to approved package content. A package's historical
acceptance does not override current permissions on package retrieval.

Research checks that the exported document and supporting references are
eligible for release. The consumer validates the package version, identity,
permissions, hashes and supported text syntax before accepting a media job.

## 3. Independent request and result contracts

`PodcastRequest` belongs to the podcast system. It explicitly carries its own
contract/schema version, request ID, idempotency key, authenticated principal,
permitted scope and media parameters, plus the consumed package ID/revision/hash
and package-contract version. It does not extend the research processing result
with voice or audio fields.

`PodcastResult` explicitly carries its contract/schema version, request ID,
job/execution-run IDs and consumed package ID/revision/hash. It reports its own
job state, prepared-text revision, audio artifact IDs/hashes, provider/runtime
version, warnings and structured failures. The podcast system retains paragraph
mapping to the package and its own immutable revision history. Research receives
no implicit writes from this result. Schema compatibility and
request/job/package
correlation are validated on status retrieval and retry, not inferred from
prose.

A media transformation cannot change accepted claims or source locators.
If a substantive correction is needed, submit a new proposal through Research's
normal contract and human review. The consumer can then explicitly use a new
released package revision; it must not rewrite the existing package.

## 4. Operational boundary

Research release succeeds once the approved immutable package is committed.
Podcast production is a separately requested downstream job; its availability
does not determine research-run success. No distributed database transaction
between these systems is required.

Choose an explicit export/import or scoped read-only API handoff for the pilot.
No direct access to research database tables. Do not introduce a message broker
until a demonstrated delivery or scale requirement justifies it.

The consumer records package receipts and applies its own idempotency/retry
rules. A render failure retries its recorded prepared-text revision rather than
requiring Research to regenerate or re-review the source document. Media status
and delivery acknowledgements remain in the podcast system.

Later supersession or withdrawal can be represented by a versioned release
status contract. The consumer's response, including whether to stop publishing
older media, must be explicit. Do not claim automatic distributed revocation
of already copied files.

## 5. Boundary acceptance

- Research starts, searches, reviews and releases text without the podcast
  service installed or reachable.
- A failed podcast job changes only media state and does not invalidate an
  accepted research document or mark its research run failed.
- Identical package references and idempotency keys do not create duplicate
  media jobs; a revised package is a distinct explicit input.
- Consumer credentials cannot mutate research notes, claims or review decisions.
- A generated narration/audio revision remains traceable to the exact released
  text, evidence and bibliography package it consumed.
- Private or unsupported packages fail validation before media processing.

See the [research concept](knowledge-management-concept.md) and
[module ownership](knowledge-system-modules.md) for the producer architecture.
