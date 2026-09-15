# Knowledge architecture review

This is a historical review, not acceptance of the subsequent article-view
revision. The [binding source-view specification](knowledge-source-view.md)
defines that revision's simplified architecture and acceptance criteria.

Updated: 2026-09-14. Status: independent agent review completed for the proposed
documentation. This is not implementation or deployment acceptance.

## Scope and method

A separately assigned review agent read the original concept, reviewed the
revised documents and checked the final contract/wording corrections. The
reviewer did not edit files or change server configuration.

Reviewed documents:

- [Knowledge management concept](knowledge-management-concept.md)
- [Research modules and skill reuse](knowledge-system-modules.md)
- [Independent podcast boundary](podcast-system-boundary.md)

The review covered Linux CPU-only assumptions, Hermes's harness role, module
responsibilities, contracts, write ownership, independent media operation,
Zotero authority, central revision history and Open Research Lab integration.

## Findings and resolutions

### P1: Media lifecycle mixed into research

The original purpose, artifacts, skills and stages included narration and
audio processing. Removed those responsibilities from Research. The independent
podcast system owns prepared narration, audio, media jobs, delivery and
recovery.
Research exports immutable released text through a versioned boundary contract.

### P1: General application core lacked internal boundaries

Replaced the general core description with explicit source, ingestion, evidence,
note, review, retrieval and text-publication modules. Defined owned writes,
operation contracts, port dependencies and transaction coordination. A small
shared kernel supplies common conventions without acquiring research logic.
Logical separation does not require a service or database for every module.

### P1: Inventory assumptions leaked into deployment architecture

Removed unrelated platform/runtime details from the research deployment.
The target is Linux without a GPU; required extraction, retrieval and text
publication need CPU acceptance. Hosted model access is explicit, while optional
embeddings and private qualitative processing require separate evaluation.

### P2: Common envelopes needed module-specific schemas

Documented each module's operation version, payload, output, preconditions,
permissions, error codes and revision expectations. Shared input/request/result
envelopes do not authorize arbitrary mutations or merge subsystem lifecycles.

### P2: Media request/result correlation was implicit

Added explicit media contract/schema versions, request/job/execution IDs and
consumed package identity/revision/hash. Status and retry validate correlation.
Research and podcast versions, requests and run states remain independently
owned.

### Non-blocking: General core wording obscured an example

The paper-to-wiki example now names Evidence, Notes, Sources and Review
operations rather than attributing all validation to an unspecified core.

## Final reviewer judgment

The reviewer confirmed that the corrections resolved the findings and reported
no remaining P1/P2 issues in the reviewed scope. Hermes remains the central
research harness; module separation, Linux CPU-only deployment and an
independent
podcast system are explicit. PostgreSQL history, Zotero authority and the Open
Research Lab publication boundary remain intact.

## Verification limits and next acceptance

The review assesses the documented architecture only. It did not execute Linux
tool smoke tests, benchmark CPU/RAM use, enforce database roles, implement
payload
schemas or verify a restore. These remain staged implementation criteria in the
main concept. Inspected skill code is not proof of server installation or
compatibility; the reuse assessment identifies required adaptations.
