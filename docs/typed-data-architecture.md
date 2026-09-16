# Typed data boundaries

Reviewed 2026-09-16. This records the implemented data boundaries and the
compatibility constraints applied during the repository-wide typing pass.

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
| Providers | Pydantic Crossref, catalog, Zotero, Docling and Marker response contracts |

Provider contracts describe the fields each adapter consumes, while ignoring
unrelated upstream fields. Existing configuration and record discriminators remain
unchanged to preserve stored schemas and request hashes. No historical data was migrated.
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

The annotation review covers application modules and tests. Pydantic models now
validate external parser, Zotero, database receipt and model response envelopes.
Database connections expose untrusted `dict[str, object]` rows, which are validated
before domain field access. Dictionary-based API and template projections use
concrete `TypedDict` contracts; persisted projections are validated with
`TypeAdapter`. This preserves existing JSON and template shapes.

Ruff enforces annotations (`ANN`), return consistency (`RET`), simplification
(`SIM`, `C4`, `PIE`), additional correctness rules (`RUF`) and performance rules
(`PERF`) alongside the original rules. Literal en dashes remain allowed because
bibliographic evidence and page-range patterns require them. All ty rules are
errors, including missing generic arguments, unsafe returns and override markers.
These checks do not establish semantic correctness: the regression suite and
existing-schema comparison remain necessary. The standalone Hermes bridge shares configuration and response contracts with
the application. Its explicit script/package imports support both launch modes;
checking external Hermes imports still requires the separately installed runtime.

## Reference discovery

Document extraction now validates recipe parameters once into
`PaperExtractionSettings`, including nested `DiscoverySettings`. Shared recipe
fields remain accepted; extraction only consumes its own validated settings.
Independent discovery-field rules use Pydantic `AfterValidator` functions.

`ReferenceSearchState` keeps each original reference, internal search identifier,
candidates, resolution and trace together. Initial and model-refined searches
share one provider loop. The search session owns pacing and request counters directly as typed dataclass
fields, alongside its explicit provider and cancellation dependencies. Query proposals and their evidence packets reuse
`PaperReference` and `Candidate` instead of constructing untyped dictionaries.
A Pydantic `TypeAdapter` bounds the planning list to 50 references; each evidence
entry admits six candidates. Planning receives that typed list directly. These limits affect model input only; the source audit
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
| 4–5 | Keep mutable counters with their owning session as typed dataclass fields; remove the redundant state envelope and constructor assignments. |
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

Tool guidance: [ty rule configuration](https://docs.astral.sh/ty/rules/),
[Ruff rules](https://docs.astral.sh/ruff/rules/).

## Model consolidation

The consolidation removes 19 model classes from the complete 157-class inventory
(including the standalone bridge), leaving 138. The earlier count of 119 described
only schemas that already existed before the comprehensive typing pass; it was
not a count of all models after that pass.

- PostgreSQL revisions validate directly as `Record`, including kind-specific
  payload decoding and datetime normalization. There is no parallel `RevisionRow`.
- Scalar IDs, revision numbers and optional strings use `TypeAdapter` instead of
  one-field model classes. No replacement wrapper or `TypedDict` is introduced.
- Search responses share one typed collection path in the existing HTTP adapter;
  providers retain their required-versus-optional array rules.
- The source article reads the actual `ExtractionJob`; a separate presentation
  state model and its database query are removed.
- Zotero bibliography and attachment requirements are checked on the existing
  validated item at the operation that requires them, without specialized subclasses.
- The application and standalone bridge share `ModelConfiguration` and
  `GenerationResponse`. Existing prompt configuration schemas remain identical.

Provider work metadata, exact-source evidence, domain records and model-generated
proposals remain separate where their fields or validation rules differ. Collapsing
optional nested API objects with `AliasPath` is deliberately limited: treating a
malformed parent as a missing optional field would weaken validation. A smaller
class count alone does not justify that change.
