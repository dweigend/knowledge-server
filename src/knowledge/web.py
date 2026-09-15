"""Disposable unstyled HTML review interface; all writes use application commands."""

import json
import re
import secrets
from html import escape
from pathlib import Path
from typing import Annotated
from urllib.error import URLError
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from knowledge import review, sources, zotero
from knowledge.application import (
    AssessmentCommand,
    EditNote,
    Knowledge,
    ReviewCommand,
)
from knowledge.config import DEFAULT_BATCH, Settings
from knowledge.contracts import Assessment, Evidence, Note, Record, Reference, Source
from knowledge.experiment_web import experiment_router
from knowledge.source_view import compose_article, preview_image
from knowledge.storage import Conflict, Database, Ledger, Missing

STATUS_LABELS = {
    "proposed": "Vorgeschlagen",
    "reviewed": "Geprüft",
    "revise": "Überarbeiten",
    "rejected": "Abgelehnt",
    "needs_review": "Erneute Prüfung nötig",
}


def citation_links(text: str) -> Markup:
    """Render validated reference tokens as links while escaping all source prose."""
    escaped = escape(text)
    return Markup(
        re.sub(
            r"\[([0-9a-f-]{36})@(\d+)\]",
            lambda match: f'<a href="/records/{match[1]}?revision={match[2]}">[Beleg]</a>',
            escaped,
        )
    )


# Route registration groups short endpoints; C901 also counts their branches.
def create_app(settings: Settings | None = None) -> FastAPI:  # noqa: C901
    """Configure the local review interface and its application dependencies."""
    settings = settings or Settings.from_environment()
    database = Database(settings.database_url)
    application = Knowledge(database)
    app = FastAPI(title="Knowledge pilot", docs_url=None, redoc_url=None)
    app.mount("/pdf-viewer", StaticFiles(directory=Path(__file__).with_name("static") / "pdfjs"))
    app.mount("/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static")
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )
    templates = Jinja2Templates(directory=Path(__file__).with_name("templates"))
    templates.env.filters["citation_links"] = citation_links
    templates.env.policies["json.dumps_kwargs"] = {"ensure_ascii": False, "sort_keys": True}
    csrf_token = secrets.token_urlsafe(32)
    app.include_router(experiment_router(settings, templates, csrf_token))

    @app.exception_handler(ValueError)
    async def invalid_request(request: Request, error: ValueError) -> Response:
        """Map application errors to stable JSON responses."""
        if request.url.path.startswith("/experiments"):
            return templates.TemplateResponse(
                request=request,
                name="experiment_error.html",
                context={"error": str(error)},
                status_code=error_status(error),
            )
        return JSONResponse({"error": str(error)}, status_code=error_status(error))

    @app.get("/health")
    def health() -> dict:
        """Check database connectivity."""
        with database.transaction() as ledger:
            ledger.connection.execute("SELECT 1")
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, batch: str = DEFAULT_BATCH, q: str = "") -> HTMLResponse:
        """Render searchable batch records with their review status."""
        with database.transaction() as ledger:
            batches = ledger.connection.execute(
                "SELECT * FROM batches ORDER BY created_at"
            ).fetchall()
            records = ledger.list(batch, query=q)
            entries = [
                {"record": record, "status": STATUS_LABELS[review.status(ledger, record)]}
                for record in records
                if record.kind != "review"
            ]
        literature = source_metadata(records, database)
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "batches": batches,
                "batch": batch,
                "entries": entries,
                "literature": literature,
                "q": q,
            },
        )

    @app.get("/runs", response_class=HTMLResponse)
    def runs(request: Request) -> HTMLResponse:
        """List private experiment logs in the local review interface."""
        root = settings.archive_root.parent / "runs"
        names = (
            sorted(path.name for path in root.iterdir() if path.is_dir()) if root.exists() else []
        )
        return templates.TemplateResponse(
            request=request, name="runs.html", context={"runs": names, "events": [], "name": None}
        )

    @app.get("/runs/{name}", response_class=HTMLResponse)
    def run_detail(request: Request, name: str) -> HTMLResponse:
        """Show model decisions, validation outcomes and note diffs without raw prompts."""
        events = read_run_events(settings.archive_root.parent / "runs", name)
        return templates.TemplateResponse(
            request=request, name="runs.html", context={"runs": [], "events": events, "name": name}
        )

    @app.get("/records/{entity_id}", response_class=HTMLResponse)
    def detail(
        request: Request,
        entity_id: UUID,
        revision: int | None = None,
        extraction_revision: int | None = None,
    ) -> HTMLResponse:
        """Render a record with its evidence, decisions and revision history."""
        with database.transaction() as ledger:
            record = ledger.get(entity_id, revision)
        if record.kind == "source":
            return templates.TemplateResponse(
                request=request,
                name="article.html",
                context=compose_article(database, record, extraction_revision),
            )
        with database.transaction() as ledger:
            dependencies = [
                ledger.get(ref.entity_id, ref.revision)
                for ref in review.dependencies(ledger, record)
            ]
            related = claim_records(ledger, record)
            decisions = [
                candidate
                for candidate in ledger.list(record.batch_id, "review")
                if candidate.payload.model_dump().get("target", {}).get("entity_id") == entity_id
            ]
            status = STATUS_LABELS[review.status(ledger, record)]
        literature = source_metadata([record, *dependencies], database)
        return templates.TemplateResponse(
            request=request,
            name="detail.html",
            context={
                "record": record,
                "literature": literature,
                "payload": record.payload.model_dump(mode="json"),
                "payload_json": record.payload.model_dump_json(indent=2),
                "dependencies": dependencies,
                "related": related,
                "decisions": decisions,
                "status": status,
                "csrf": csrf_token,
                "request_id": str(uuid4()),
                "history": application.history(entity_id),
            },
        )

    @app.get("/api/records/{entity_id}")
    def read_record(entity_id: UUID, revision: int | None = None) -> dict:
        """Return a record with its status and pinned dependencies."""
        with database.transaction() as ledger:
            record = ledger.get(entity_id, revision)
            return {
                "record": record.model_dump(mode="json"),
                "status": review.status(ledger, record),
                "dependencies": [
                    ref.model_dump(mode="json") for ref in review.dependencies(ledger, record)
                ],
            }

    @app.get("/api/requests/{request_id}")
    def receipt(request_id: str) -> dict:
        """Return the result of an accepted command."""
        with database.transaction() as ledger:
            row = ledger.get_receipt(request_id)
            if not row:
                raise Missing("Request not accepted")
            return {"request_id": row["request_id"], "result": row["result"]}

    @app.get("/sources/{entity_id}/{variant}/view", response_class=HTMLResponse)
    def source_viewer(
        request: Request,
        entity_id: UUID,
        variant: str,
        revision: int | None = None,
        page: int = 1,
        extraction_revision: int | None = None,
    ) -> HTMLResponse:
        """Show the pinned Zotero PDF through the self-hosted PDF.js viewer."""
        if variant not in {"original", "clean"} or page < 1:
            raise ValueError("Unknown PDF variant or invalid page")
        with database.transaction() as ledger:
            record = ledger.get(entity_id, revision)
            sources.zotero_reference(ledger, record)
        pdf_url = f"/sources/{entity_id}/{variant}?revision={record.revision}"
        return templates.TemplateResponse(
            request=request,
            name="pdf.html",
            context={
                "record": record,
                "pdf_url": pdf_url,
                "encoded_pdf_url": quote(pdf_url, safe=""),
                "page": page,
                "extraction_revision": extraction_revision,
            },
        )

    @app.get("/sources/{entity_id}/previews/{block_id}")
    def source_preview(
        entity_id: UUID, block_id: str, revision: int, extraction_revision: int
    ) -> Response:
        """Return a regenerated original figure or table region without retaining a PDF copy."""
        return Response(
            preview_image(database, entity_id, revision, block_id, extraction_revision),
            media_type="image/png",
        )

    @app.get("/sources/{entity_id}/{variant}")
    def source_file(entity_id: UUID, variant: str, revision: int | None = None) -> FileResponse:
        """Resolve the pinned Zotero attachment and verify its bytes before serving it."""
        with database.transaction() as ledger:
            record = ledger.get(entity_id, revision)
            reference = sources.zotero_reference(ledger, record)
        return FileResponse(zotero.verified_pdf(reference, variant), media_type="application/pdf")

    @app.post("/records/{entity_id}/review")
    def record_review(
        entity_id: UUID,
        revision: Annotated[int, Form()],
        verdict: Annotated[str, Form()],
        comment: Annotated[str, Form()],
        csrf: Annotated[str, Form()],
        request_id: Annotated[str, Form()],
    ) -> RedirectResponse:
        """Submit an attributed human decision after validating the form token."""
        if not secrets.compare_digest(csrf, csrf_token):
            raise HTTPException(403, "Invalid form token")
        with database.transaction() as ledger:
            batch_id = ledger.get(entity_id).batch_id
        application.decide(
            request_id,
            batch_id,
            ReviewCommand(
                target=Reference(entity_id=entity_id, revision=revision),
                verdict=verdict,
                comment=comment,
            ),
            "human:local",
        )
        return RedirectResponse(f"/records/{entity_id}", status_code=303)

    @app.post("/records/{entity_id}/edit")
    def edit_record(
        entity_id: UUID,
        revision: Annotated[int, Form()],
        content: Annotated[str, Form()],
        csrf: Annotated[str, Form()],
        request_id: Annotated[str, Form()],
    ) -> RedirectResponse:
        """Submit an editable record after validating the form token."""
        if not secrets.compare_digest(csrf, csrf_token):
            raise HTTPException(403, "Invalid form token")
        with database.transaction() as ledger:
            record = ledger.get(entity_id)
        save_edit(application, record, revision, content, request_id)
        return RedirectResponse(f"/records/{entity_id}", status_code=303)

    return app


def error_status(error: ValueError) -> int:
    """Map known application failures to HTTP status codes."""
    if isinstance(error, Conflict):
        return 409
    if isinstance(error, Missing):
        return 404
    return 422


def claim_records(ledger: Ledger, record: Record) -> list[Record]:
    """Find the evidence and assessments attached to a claim."""
    if record.kind != "claim":
        return []
    return [
        candidate
        for candidate in ledger.list(record.batch_id)
        if isinstance(candidate.payload, (Evidence, Assessment))
        and candidate.payload.claim.entity_id == record.entity_id
    ]


def parse_edit(record: Record, expected: Reference, content: str) -> EditNote | AssessmentCommand:
    """Validate submitted JSON against the editable record type."""
    payload = json.loads(content)
    if record.kind == "note":
        return EditNote(expected=expected, note=Note.model_validate(payload))
    if record.kind == "assessment":
        return AssessmentCommand(expected=expected, assessment=Assessment.model_validate(payload))
    raise ValueError("Only notes and assessments can be edited in this pilot UI")


def save_edit(
    application: Knowledge,
    record: Record,
    revision: int,
    content: str,
    request_id: str,
) -> None:
    """Apply a human edit and translate malformed content to HTTP errors."""
    expected = Reference(entity_id=record.entity_id, revision=revision)
    try:
        command = parse_edit(record, expected, content)
        if isinstance(command, EditNote):
            application.edit_note(request_id, record.batch_id, command, "human:local")
            return
        application.assess(request_id, record.batch_id, command, "human:local")
    except (json.JSONDecodeError, ValidationError) as error:
        raise HTTPException(422, str(error)) from error


def source_metadata(records: list[Record], database: Database) -> dict:
    """Read live literature while retaining access to snapshots if Zotero is unavailable."""
    return {
        str(record.entity_id): source_description(record, database)
        for record in records
        if isinstance(record.payload, Source)
    }


def source_description(record: Record, database: Database) -> dict:
    """Show an explicit availability error instead of substituting cached literature."""
    try:
        with database.transaction() as ledger:
            reference = sources.zotero_reference(ledger, record)
        return zotero.get_bibliography(reference).model_dump()
    except (URLError, OSError, ValueError) as error:
        return {"title": "Zotero-Daten nicht verfügbar", "error": str(error)}


def read_run_events(root: Path, name: str) -> list[dict]:
    """Read chronological JSONL events only from a direct run directory."""
    directory = (root / name).resolve()
    if directory.parent != root.resolve() or not directory.is_dir():
        raise Missing("Unknown run")
    events = [
        json.loads(line)
        for path in directory.rglob("events.jsonl")
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    return sorted(events, key=lambda event: event["time"])
