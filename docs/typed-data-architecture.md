# Typed data boundaries

Reviewed 2026-09-16 against `6c3c2ed`. This replaces the longer plan deleted in
`2596ce8`; it records implemented boundaries and remaining migration work.

Validate external structured input at its owner with Pydantic, retain the model
inside the workflow, and serialize only for storage or output. Use existing
models and `TypeAdapter`, without forwarding wrappers or parallel representations.
Contextual revision, hash, citation and transaction checks remain domain rules.

| Boundary | Current implementation |
| --- | --- |
| HTTP/CLI JSON | Direct model/list validation; typed history until export |
| Environment | `BaseSettings`; required locations and one path normalization |
| Import/resume | Retain `PreparedImport`; load saved state only on resume |
| Pipeline inputs | Runner validates outputs; steps receive typed models |
| Persistence | Existing record, extraction, configuration and attempt types |
| Providers | Typed results where present; raw provider subsets remain |

The historical plan's fully typed provider payloads, discriminated configuration
and attempt variants, and single record discriminator are **not implemented**.
Replacing these requires coordinated caller/storage changes and schema acceptance;
adding parallel DTOs would defeat this cleanup. No historical data was migrated.
Legacy source readers remain necessary for immutable citations. Local template
contexts and callable execution state do not need additional Pydantic envelopes.

All application Python files were reviewed, split across core/storage/maintenance,
workflows/document processing/literature, experiments/model/runtime, and interfaces.
Prompts, SQL, templates and application CSS were included. Bundled PDF.js remains
an unchanged upstream dependency. Removed code includes backup and parser helpers,
duplicate HTML parsing, repeated model conversions, repeated dependency traversal
state, repeated recipe reads, duplicate logging serialization and unused CSS.

Existing model and pipeline output schemas and canonical hash algorithms are
preserved; runtime settings gain their own schema. Source edits intentionally
change the existing code fingerprint used by experiments. Production Hermes/OCR
acceptance remains separate from fixture tests; the local Hermes runtime is absent.

## Python annotations

Use `Final[int]`, `Final[str]` and other concrete types for module constants that
must not be rebound. `Literal` describes a restricted set of accepted values,
such as provider names; it is not a substitute for constant declarations. A
`Final` binding does not make the contents of a list or dictionary immutable.

Keep function inputs and results concrete where their shape is known. Reuse
existing Pydantic models for structured boundaries and `Mapping[str, object]`
for untrusted objects that are immediately validated. Use `JsonValue` only for
actual JSON values, not database rows or template contexts containing Python
objects. Dynamic third-party payloads need schema work rather than unchecked
casts or annotations that merely conceal missing validation.

Pydantic schemas, FastAPI response handling, stored JSON and model-request hashes
must remain stable during annotation-only changes. An annotation that changes
runtime validation is a contract change and needs separate review.

The annotation review covers application modules and test support. Remaining
dynamic dictionaries are concentrated in external Docling/Marker/Zotero payloads,
heterogeneous PostgreSQL rows, Jinja view contexts and merged experiment inspection
results. Replacing these requires concrete boundary contracts; no blanket casts,
type-check suppressions or misleading JSON annotations were added.

## Reference discovery

Document extraction now validates recipe parameters once into
`PaperExtractionSettings`, including nested `DiscoverySettings`. Shared recipe
fields remain accepted; extraction only consumes its own validated settings.
Independent discovery-field rules use Pydantic `AfterValidator` functions.

`ReferenceSearchState` keeps each original reference, internal search identifier,
candidates, resolution and trace together. Initial and model-refined searches
share one provider loop. `LookupState` owns per-run pacing and request counters;
the session remains ordinary Python orchestration with explicit provider and
cancellation dependencies. Query proposals and their evidence packets reuse
`PaperReference` and `Candidate` instead of constructing untyped dictionaries.
`ReferenceQueryBatch` bounds the planning input to 50 references and six candidates
per reference. Planning receives this model directly, rather than separate reference
and candidate collections. These limits affect model input only; the source audit
retains all collected candidates.

Crossref now shares the bounded HTTP transport with the other discovery providers.
Its response schemas validate deposited fields before normalization. Provider
transport and validation failures remain cacheable; unexpected `KeyError` and
`TypeError` propagate instead of masquerading as unresolved sources. Cancellation
also propagates and is never written to the negative cache.

Existing output schemas, field defaults, whitespace policies and cache hashes
remain unchanged. Planning packets deliberately retain the previous `json.dumps`
representation: replacing it with `model_dump_json()` would change cache keys.
Trusted internal copies use `model_copy`; external input and constrained settings
use validation. `Contract` is not a universal base because its whitespace trimming
would change exact evidence. No generic model or cache hierarchy is introduced.

### Review comment coverage

| Comment | Applied change |
| --- | --- |
| 1–2 | Keep settings declarative; separate field validators with early returns. |
| 3 | Use independent guard clauses when selecting the richest matching candidate. |
| 4–5 | Centralize mutable counters in `LookupState`; remove repetitive constructor assignments. Executable provider dependencies remain in the session. |
| 6 | Separate lookup orchestration, cached results and pacing/budget checks. |
| 7 | Keep request accounting separate from redacted provider failure handling; catch only recoverable transport/validation errors. |
| 8 | Separate initial identity lookup from the shared fallback provider loop. |
| 9–10 | Apply one proposal at a time through the same provider loop as ordinary searches. |
| 11 | Retain one typed state per source throughout recovery, identification, refinement and persistence; read its source hash instead of passing duplicate parameters. |
| 12–13 | Restore original IDs before collection; handle duplicate-ID collisions with a flat guarded loop. |
| 14 | Use a bounded planning schema and typed Crossref response schemas; reuse the existing HTTP implementation. |
| 15 | Validate extraction settings once and separate document analysis from literature enrichment. |

References: [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/),
[validators](https://docs.pydantic.dev/latest/concepts/validators/),
[TypeAdapter](https://docs.pydantic.dev/latest/concepts/type_adapter/),
[BaseSettings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/),
[record integrity](knowledge-contracts.md).
