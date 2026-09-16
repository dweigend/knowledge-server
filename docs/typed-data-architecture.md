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

Existing output schemas, field defaults, whitespace policies and cache hashes
remain unchanged. Planning packets deliberately retain the previous `json.dumps`
representation: replacing it with `model_dump_json()` would change cache keys.
Trusted internal copies use `model_copy`; external input and constrained settings
use validation. `Contract` is not a universal base because its whitespace trimming
would change exact evidence. No generic model or cache hierarchy is introduced.

References: [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/),
[validators](https://docs.pydantic.dev/latest/concepts/validators/),
[TypeAdapter](https://docs.pydantic.dev/latest/concepts/type_adapter/),
[BaseSettings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/),
[record integrity](knowledge-contracts.md).
