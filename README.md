# Knowledge Server

A self-hosted Python knowledge system combining a Zettelkasten, wiki and
revisioned claims with inspectable evidence. Zotero owns literature metadata and
PDFs; the knowledge database stores references, source passages and derived work.

**Status: early alpha.** The core import, review and consolidation workflows
exist. Structured document extraction and source views are being integrated;
full corpus acceptance and the newer modular design are not complete.

The binding storage target is an [own Zotero WebDAV file server](docs/knowledge-webdav-sync.md)
for personal-library PDFs, with Zotero.org data sync and official iPad support.
Deployment and migration are pending.

## What it does

- Track claims, supporting or contradicting evidence, and explicit assessments.
- Preserve revision-pinned citations and human review decisions.
- Propose updates to existing notes through an inspectable consolidation run.
- Read PDFs through Zotero using the bundled PDF.js viewer.
- Run optional Docling/Marker extraction jobs with versioned snapshots.

The web interface is deliberately plain HTML. It is a single-user review tool
with no login system. Bind it to loopback and access it through an SSH tunnel;
it is not ready for direct public Internet exposure.

## Quick start

Requirements: Python 3.13+, [uv](https://docs.astral.sh/uv/), PostgreSQL,
and [Zotero Desktop](https://www.zotero.org/download/) for literature access.
Use Linux for the optional extraction worker. Reading records, exporting and
initializing the database do not need a model or Hermes.

```sh
git clone https://github.com/dweigend/knowledge-server.git
cd knowledge-server
uv sync --locked
cp .env.example .env
```

Create a PostgreSQL role and two databases using your usual administrator
account. For an existing local PostgreSQL installation, one example is:

```sh
createuser knowledge
createdb --owner=knowledge knowledge
createdb --owner=knowledge knowledge_test
```

Configure database authentication separately, then edit `.env` for your
connection, paths and Zotero settings. Environment files are loaded explicitly:

```sh
set -a
. ./.env
set +a
mkdir -p "$KNOWLEDGE_ARCHIVE_ROOT"
uv run knowledge init
uv run uvicorn knowledge.web:create_app --factory --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765/>. The pilot review UI currently uses German labels.
An empty database is expected on first start.
No research documents, model weights, credentials or database dumps are shipped.

## Import and consolidate

Install Hermes separately. The current adapter requires the reviewed
`gpt-5.6-luna` / `openai-codex` configuration and uses Hermes authentication.
It does not yet provide a generic model selector. Override
`KNOWLEDGE_HERMES_PYTHON` if Hermes uses a different Python environment.

Enable Zotero's local API, keep Zotero on the same machine as this application,
and configure authorized write access for imports. Attachment resolution uses
local file URLs returned by Zotero. See the
[Zotero API documentation](https://www.zotero.org/support/dev/web_api/v3/local_api).
Poppler tools (`pdftotext`, `pdftoppm`) are needed for PDF processing.

Create a private `selection.json` containing absolute paths to your own PDFs:

```json
[
  {"path": "/absolute/path/to/article.pdf", "remove_cover": false}
]
```

```sh
uv run knowledge import --batch research --input selection.json \
  --output .local/runs/import-01
uv run knowledge consolidate --batch research --output .local/runs/consolidation-01
uv run knowledge export --batch research --output .local/exports/research
```

Consolidation revises existing notes; it is not an automatic wiki bootstrap.
Select a batch using `/?batch=research` in the web interface.
Run logs contain model inputs and outputs and must stay private. Reusing the
same run directory resumes a run. `knowledge --help` lists the command surface.
The historical `pilot` preset requires its own supplied source directory.

## Architecture and development

The existing Python package name remains `knowledge` and its distribution name
remains `hermes-knowledge` to avoid an unnecessary compatibility change.

| Area | Modules |
| --- | --- |
| Contracts and persistence | `contracts.py`, `storage.py`, `schema.sql` |
| Knowledge rules | `sources.py`, `evidence.py`, `notes.py`, `review.py` |
| Workflows | `application.py`, `import_workflow.py`, `consolidation.py` |
| External systems | `zotero.py`, `generation.py`, `hermes_bridge.py` |
| Extraction | `document_*.py`, `extraction_*.py`, `marker_parser.py` |
| User interface | `web.py`, `source_view.py`, `templates/` |

Start with the [documentation index](docs/README.md),
[contribution guide](CONTRIBUTING.md) and [Python coding rules](AGENTS.md).
See [deployment](deploy/README.md) for the optional Linux worker and backups.

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked ty check --exclude src/knowledge/hermes_bridge.py
uv run --locked pytest
uv build
```

Tests require `KNOWLEDGE_TEST_DATABASE_URL`; each database test uses an isolated
schema. GitHub Actions supplies PostgreSQL. Hermes live calls and OCR model
quality are separate integration checks, not claims made by the unit suite.

## License

Original project code is under the [MIT license](LICENSE).
Bundled PDF.js and optional extraction dependencies retain their own terms;
see [third-party notices](THIRD_PARTY_NOTICES.md).
