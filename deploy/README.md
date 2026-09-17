# Deployment

The basic app needs PostgreSQL and Zotero Desktop on the application host.
Manage those services with your platform's existing tools. The templates here
only run the web application and its optional document worker.

Clone into `~/projects/knowledge-server` or edit the template paths. Install
the application with `uv sync --locked`. Copy your private environment file to
`~/.config/knowledge-server/environment` with absolute paths, no shell expansion,
and permissions `0600`. Install the required templates in
`~/.config/systemd/user/`, then run `systemctl --user daemon-reload`.
Enable the web service with `systemctl --user enable --now knowledge-web`.
Start PostgreSQL and Zotero before using the app.

## Planned Zotero WebDAV storage

An [own WebDAV file server](../docs/knowledge-webdav-sync.md) is the binding
target for personal-library attachments and iPad access. This is not provisioned
by the current service templates. Follow the decision document for transport,
annotation intake, backup coverage and verified migration requirements.

## Optional scientific-PDF service

The experiment workbench can use GROBID for document structure, paper metadata,
references and citation links. It is an independent HTTP service; the application
selects its address through `KNOWLEDGE_GROBID_URL`. Installing Python dependencies
does not start GROBID. Keep this endpoint private: uploaded PDFs are sent to it.

With Docker running, start the supplied development service from the repository
root:

```sh
docker compose -f deploy/grobid.compose.yml up -d
curl --fail http://127.0.0.1:8070/api/isalive
```

The template pins `grobid/grobid:0.9.1-crf`, binds only to loopback and limits
resources to two CPUs and 4 GB RAM. It uses CPU models and works under amd64
emulation on Apple Silicon. The CRF image is a modest development baseline;
upstream recommends the substantially larger full image for better metadata,
reference and citation accuracy. Evaluate extraction quality on your papers
before choosing a production model image. See the official
[Docker documentation](https://grobid.readthedocs.io/en/latest/Grobid-docker/).

The adapter disables external bibliographic consolidation. Extraction still needs
review: missing metadata and unmatched citation markers must not be treated as
verified references. Existing Poppler extraction remains separately available.

Inspect and stop only this service with:

```sh
docker compose -f deploy/grobid.compose.yml logs --tail 100
docker compose -f deploy/grobid.compose.yml down
```

For a service already running on another trusted host, use an SSH tunnel and keep
the same local application URL:

```sh
ssh -N -L 127.0.0.1:8070:127.0.0.1:8070 YOUR_HOST
```

## Optional extraction worker

The worker currently targets Linux with systemd user services and CPU inference.
Install Poppler (`pdftotext`, `pdftoppm`) and use
`uv sync --locked --group extraction`.
The current Marker adapter also expects llama.cpp build `b10976` binaries in
`<runtime-root>/extraction-tools/llama-b10976`; install that upstream runtime
separately. Runtime root is the parent of `KNOWLEDGE_ARCHIVE_ROOT`.
`uv sync` alone does not provision this inference runtime.

Tools download model weights on first use. Keep them outside the Git repository.
The adapter stores third-party model assets under the runtime root; inspect the
installed Surya release for any additional runtime paths before production use.
Each tool runs in a bounded systemd unit with a two-hour timeout, 12 GB memory
limit and four CPU cores. These are conservative pilot defaults.

Queue an existing source with `knowledge extract --entity SOURCE_UUID`.
Run `knowledge extract-worker` to process queued work. The supplied timer can
invoke the worker periodically; enable it only after verifying one source and
the extraction quality checks on your own installation. Full corpus acceptance
is still pending in the original pilot.

## Backups

`knowledge backup --output /private/backups` uses PostgreSQL tools from PATH
or `KNOWLEDGE_POSTGRES_BIN`. Set `KNOWLEDGE_ZOTERO_LIBRARY` to the actual local
Zotero data directory. This command is currently a Linux operational helper:
it stops and restarts the `knowledge-zotero` user service around its SQLite
snapshot. Use it only when Zotero is managed by that service and no other
process writes the library. Configure that service yourself for your platform.

The database role needs permission to create a temporary restore database.
The command verifies checksums, restores into that temporary database and
removes the restore target. Backups contain private literature and model logs;
they are recovery artifacts, not another literature workspace.
