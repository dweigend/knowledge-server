# Contributing

Use Python 3.13 and `uv sync --locked`. Follow [AGENTS.md](AGENTS.md): short
functions, explicit names, flat control flow and one responsibility per module.
Reuse existing code before introducing dependencies or abstractions.

Install Poppler (`pdftoppm`) for the synthetic PDF page-mapping tests.
Configure an isolated PostgreSQL database through
`KNOWLEDGE_TEST_DATABASE_URL`. Run the checks in the README before submitting
a change. Keep source quotations, stored contracts and revision semantics
stable; document and test deliberate migrations.

Include a concise description of the problem, changed behavior and verification
in pull requests. Distinguish tested behavior from future architectural plans.
Use synthetic fixtures rather than private papers or model transcripts. Never
commit credentials, PDFs, local Zotero libraries, caches or database exports.

The Hermes bridge needs its installed runtime for live checks. The default test
suite does not download OCR models or call a paid model service.
