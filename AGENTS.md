# Python coding rules

## Structure

- Give each function one concrete job. Its name should explain the outcome.
- Prefer 10-25 lines of executable code. Split distinct tasks, not every step.
- Keep control flow flat with early returns. Combine adjacent resource contexts.
- Retain explicit transaction and cleanup scopes; never weaken them to save lines.
- Use blank lines between input checks, the main work and the result.
- Use simple functions and the existing modules. Add no generic service layers.
- Remove helpers that only forward arguments without clarifying a boundary.
- Keep FastAPI route registration together; route bodies should remain short.

## Names and documentation

- Use English names that identify domain meaning, units and revision semantics.
- Do not rename stored fields casually: they are data contracts, not local names.
- Give public functions and methods a short imperative docstring ending in a period.
- Describe public classes by responsibility. Explain ambiguous fields and units.
- Add a second paragraph only for a non-obvious constraint or side effect.
- Do not repeat parameter types or add boilerplate Args/Returns sections.
- Descriptive test names replace docstrings for tests and fixtures.
- Pydantic class docstrings enter JSON schemas and therefore model request hashes.
  Review those changes; never silently regenerate existing knowledge records.

## Simplicity and errors

- Keep only code required by a current workflow or a concrete integrity rule.
- Preserve exact quotations, revision checks and atomic request acceptance.
- Use ValueError for invalid input, Conflict for stale requests and Missing for
  absent records. Do not add exception classes for individual validation rules.
- Group related validation rules. Keep messages specific enough to fix the input.
- Catch errors only where a recovery action exists, and make that action explicit.
- Do not hide failed imports or substitute a different source after a citation fails.

## Verification

Run from the repository root:

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked ty check --exclude src/knowledge/hermes_bridge.py
uv run --locked pytest
```

Set `KNOWLEDGE_TEST_DATABASE_URL` to the isolated test database before pytest.
The Hermes bridge uses the installed Hermes environment and needs its own check.
Do not introduce another formatter, linter or custom style-checking framework.
