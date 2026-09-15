"""Render manual experiments and configuration history through shared operations."""

import json
import secrets
from pathlib import Path
from typing import cast

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData, UploadFile

from knowledge import experimentation as experiments
from knowledge.config import Settings
from knowledge.contracts import Record
from knowledge.generation import ModelConfiguration
from knowledge.paper_view import render_paper_markdown
from knowledge.pipeline_steps import OUTPUT_SCHEMAS, validate_step_parameters
from knowledge.prompt_registry import (
    AuthorRules,
    ConfigRevision,
    Recipe,
    Step,
    activate_revision,
    configuration_status,
    get_revision,
    save_revision,
    seed_defaults,
)
from knowledge.storage import Conflict, Missing

STEP_LABELS = {
    "extract_text": "PDF text",
    "segment_blocks": "Information blocks",
    "formulate_claims": "Claims & evidence",
    "find_knowledge": "Find knowledge",
    "select_entries": "Select entries",
    "propose_changes": "Propose changes",
    "prepare_writing": "Cited points",
    "draft_text": "Write prose",
}
MAX_UPLOAD_BYTES = 64 * 1024 * 1024


def required_text(form: FormData, name: str, *, allow_empty: bool = False) -> str:
    """Read a required text field without converting missing values into server errors."""
    value = form.get(name)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"Missing required form field: {name}")
    return value


async def checked_form(request: Request, token: str) -> FormData:
    """Validate the shared form token before accepting any experiment mutation."""
    form = await request.form()
    if not secrets.compare_digest(str(form.get("csrf", "")), token):
        raise HTTPException(403, "Invalid form token; reload this page and try again.")
    return form


def latest_recipe(step: str) -> tuple[ConfigRevision, Recipe]:
    """Read the latest saved recipe for editing without activating it."""
    record = get_revision("recipe", step)
    return record, Recipe.model_validate(record.payload)


def step_cards(attempts: list[dict]) -> list[dict]:
    """Compose operation controls with their latest attempt and exact prompt draft."""
    cards = []
    for step, title in STEP_LABELS.items():
        record, recipe = latest_recipe(step)
        prompt = get_revision("prompt", recipe.prompt_name, recipe.prompt_revision)
        history = [attempt for attempt in attempts if attempt["step"] == step]
        cards.append(
            {
                "step": step,
                "title": title,
                "record": record,
                "recipe": recipe,
                "prompt": prompt,
                "latest_prompt": get_revision("prompt", recipe.prompt_name),
                "latest": history[-1] if history else None,
                "history": history,
            }
        )
    return cards


def save_step_configuration(step: str, form: FormData) -> ConfigRevision:
    """Save typed prompt and recipe revisions with explicit optimistic revision checks."""
    if step not in STEP_LABELS:
        raise ValueError("Unknown pipeline step")
    previous, recipe = latest_recipe(step)
    expected = int(required_text(form, "expected_revision"))
    if previous.revision != expected:
        raise Conflict("Recipe changed in another page; reload before saving.")
    instructions = required_text(form, "instructions")
    prompt_revision = int(required_text(form, "prompt_revision"))
    if get_revision("prompt", recipe.prompt_name).revision != prompt_revision:
        raise Conflict("Prompt changed in another page; reload before saving.")
    configuration = ModelConfiguration(
        model=str(form.get("model", "")) or None,
        provider=str(form.get("provider", "")) or None,
        max_attempts=int(str(form.get("max_attempts", "2"))),
        timeout_seconds=float(str(form.get("timeout_seconds", "240"))),
        allowed_tools=json.loads(str(form.get("allowed_tools", "[]"))),
    )
    parameters = json.loads(str(form.get("parameters", "{}")))
    if step == "extract_text" and "document_provider" in form:
        parameters = {"document_provider": required_text(form, "document_provider")}
        if parameters["document_provider"] == "grobid":
            parameters["service_url"] = required_text(form, "service_url")
    rules_name = str(form.get("author_rules_name", "")) or None
    rules_revision = int(required_text(form, "author_rules_revision")) if rules_name else None
    updated = Recipe(
        step=cast(Step, step),
        prompt_name=recipe.prompt_name,
        prompt_revision=recipe.prompt_revision,
        model=configuration,
        parameters=parameters,
        output_schema=OUTPUT_SCHEMAS[step],
        author_rules_name=rules_name,
        author_rules_revision=rules_revision,
    )
    validate_step_parameters(updated)
    if updated.output_schema != OUTPUT_SCHEMAS[step]:
        raise ValueError("Recipe output format does not match the selected step")
    if rules_name is not None and rules_revision is not None:
        AuthorRules.model_validate(get_revision("author_rules", rules_name, rules_revision).payload)
    note_name = updated.parameters.get("note_prompt_name")
    note_revision = updated.parameters.get("note_prompt_revision")
    if isinstance(note_name, str) and isinstance(note_revision, int):
        get_revision("prompt", note_name, note_revision)
    prompt = save_revision("prompt", recipe.prompt_name, {"text": instructions}, prompt_revision)
    updated.prompt_revision = prompt.revision
    return save_revision("recipe", step, updated.model_dump(mode="json"), expected)


def selected_attempt(root: Path, run_id: str, attempt_id: str) -> dict:
    """Resolve one attempt only within its owned experiment."""
    manifest = experiments.read_manifest(root, run_id)
    if manifest.get("legacy") or manifest.get("cleanup_pending"):
        raise Missing("This source has no current experiment attempts")
    for attempt in experiments.read_attempts(root, run_id):
        if attempt["id"] == attempt_id:
            return attempt
    raise Missing("Unknown experiment attempt")


def prepare_comparison(
    root: Path, selections: list[str], recipe: ConfigRevision
) -> list[tuple[str, str]]:
    """Validate every baseline before preparing a cancellable batch of manual variants."""
    baselines = []
    for selection in selections:
        run_id, attempt_id = selection.split(":", 1)
        attempt = selected_attempt(root, run_id, attempt_id)
        if attempt["step"] != recipe.payload["step"]:
            raise ValueError("All baselines must use the same step as the variant recipe")
        baselines.append((run_id, attempt))
    if len({run_id for run_id, _ in baselines}) != len(baselines):
        raise ValueError("Choose only one baseline per source for a comparison run")
    if len({attempt["knowledge_hash"] for _, attempt in baselines}) > 1:
        raise ValueError("Comparison sources must share the same pinned starting knowledge")
    created = []
    try:
        for run_id, baseline in baselines:
            identifier = experiments.prepare_attempt(
                root, run_id, baseline["step"], recipe, input_attempts=baseline["inputs"]
            )
            created.append((run_id, identifier))
    except ValueError:
        for run_id, identifier in created:
            experiments.request_cancel(root, run_id, identifier)
            experiments.recover_attempt(root, run_id, identifier)
        raise
    return created


async def validated_uploads(uploads: list[str | UploadFile]) -> list[tuple[str, UploadFile]]:
    """Check every uploaded PDF before creating the first experiment."""
    if not uploads or any(not isinstance(source, UploadFile) for source in uploads):
        raise ValueError("Choose at least one PDF source")
    if len(uploads) > 12:
        raise ValueError("Choose at most twelve sources at a time")
    validated = []
    for upload in uploads:
        source = cast(UploadFile, upload)
        filename = source.filename or "source.pdf"
        content = await source.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError("PDF exceeds the 64 MiB source limit")
        if not filename.lower().endswith(".pdf") or not content.startswith(b"%PDF-"):
            raise ValueError(f"{filename}: choose a .pdf file with a valid PDF header")
        await source.seek(0)
        validated.append((filename, source))
    return validated


def experiment_router(  # noqa: C901
    settings: Settings, templates: Jinja2Templates, csrf_token: str
) -> APIRouter:
    """Register thin experiment routes using the existing application's form protection."""
    router = APIRouter(prefix="/experiments")
    root = settings.archive_root
    templates.env.filters["paper_markdown"] = render_paper_markdown
    seed_defaults()

    def render(request: Request, name: str, **context: object) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name=name,
            context={
                "csrf": csrf_token,
                "step_labels": STEP_LABELS,
                **context,
            },
        )

    @router.get("", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        """Show source selection without starting a model or pipeline operation."""
        return render(
            request,
            "experiments.html",
            experiment=None,
            runs=experiments.list_experiments(root),
            cards=step_cards([]),
        )

    @router.post("")
    async def upload(request: Request) -> RedirectResponse:
        """Copy bounded PDF sources and an optional reviewed knowledge snapshot."""
        form = await checked_form(request, csrf_token)
        uploads = await validated_uploads(form.getlist("sources"))
        supplied_knowledge = json.loads(str(form.get("knowledge", "[]")))
        if not isinstance(supplied_knowledge, list):
            raise ValueError("Starting knowledge must be a JSON list of revisioned records")
        knowledge = [Record.model_validate(record) for record in supplied_knowledge]
        run_id = ""
        for filename, source in uploads:
            content = await source.read(MAX_UPLOAD_BYTES + 1)
            run_id = experiments.create_experiment(root, filename, content, seed_records=knowledge)
        return RedirectResponse(f"/experiments/{run_id}", 303)

    @router.get("/settings", response_class=HTMLResponse)
    def settings_view(
        request: Request, kind: str = "recipe", name: str = "", revision: int | None = None
    ) -> HTMLResponse:
        """Show immutable saved revisions and active defaults separately."""
        if kind not in {"recipe", "prompt", "author_rules"}:
            raise ValueError("Unknown configuration kind")
        selected = get_revision(kind, name, revision) if name else None
        return render(
            request,
            "experiment_settings.html",
            configurations=configuration_status(),
            selected=selected,
        )

    @router.post("/settings/activate")
    async def activate(request: Request) -> RedirectResponse:
        """Activate one saved configuration only after checking its previous default."""
        form = await checked_form(request, csrf_token)
        kind = required_text(form, "kind")
        if kind not in {"recipe", "prompt", "author_rules"}:
            raise ValueError("Unknown configuration kind")
        activate_revision(
            kind,
            required_text(form, "name"),
            int(required_text(form, "revision")),
            int(required_text(form, "expected_revision")),
        )
        return RedirectResponse("/experiments/settings", 303)

    @router.post("/settings/rules")
    async def author_rules(request: Request) -> RedirectResponse:
        """Save private author instructions and user-chosen examples as a new revision."""
        form = await checked_form(request, csrf_token)
        save_revision(
            "author_rules",
            required_text(form, "name"),
            {
                "text": required_text(form, "text"),
                "examples": json.loads(str(form.get("examples", "[]"))),
            },
            int(required_text(form, "expected_revision")),
        )
        return RedirectResponse("/experiments/settings", 303)

    @router.get("/compare", response_class=HTMLResponse)
    def comparison(request: Request, step: str = "segment_blocks") -> HTMLResponse:
        """Compare one operation's attempts by source and pinned input revisions."""
        if step not in STEP_LABELS:
            raise ValueError("Unknown pipeline step")
        rows = []
        for run in experiments.list_experiments(root):
            if run.get("legacy") or run.get("cleanup_pending"):
                continue
            attempts = [a for a in experiments.read_attempts(root, run["id"]) if a["step"] == step]
            if attempts:
                rows.append({"run": run, "attempts": attempts})
        return render(
            request,
            "experiment_compare.html",
            rows=rows,
            step=step,
            recipes=[
                r
                for r in configuration_status("recipe")
                if Recipe.model_validate(r["payload"]).step == step
            ],
        )

    @router.post("/compare")
    async def compare_variant(request: Request, background: BackgroundTasks) -> RedirectResponse:
        """Run an explicitly selected variant on each selected source's fixed inputs."""
        form = await checked_form(request, csrf_token)
        selected = form.getlist("attempts")
        if not 1 <= len(selected) <= 12:
            raise ValueError("Select one to twelve baseline attempts")
        recipe = get_revision(
            "recipe",
            required_text(form, "recipe_name"),
            int(required_text(form, "recipe_revision")),
        )
        prepared = prepare_comparison(root, [str(item) for item in selected], recipe)
        for run_id, identifier in prepared:
            background.add_task(experiments.execute_attempt, root, run_id, identifier)
        return RedirectResponse(f"/experiments/compare?step={recipe.payload['step']}", 303)

    @router.get("/{run_id}", response_class=HTMLResponse)
    def detail(request: Request, run_id: str) -> HTMLResponse:
        """Read source-specific results and dependency state without executing steps."""
        manifest = experiments.read_manifest(root, run_id)
        unavailable = manifest.get("legacy") or manifest.get("cleanup_pending")
        attempts = [] if unavailable else experiments.read_attempts(root, run_id)
        return render(
            request,
            "experiments.html",
            experiment=manifest,
            runs=experiments.list_experiments(root),
            cards=[] if unavailable else step_cards(attempts),
        )

    @router.get("/{run_id}/pdf")
    def pdf(run_id: str) -> FileResponse:
        """Serve the owned source PDF for manual evidence inspection."""
        manifest = experiments.read_manifest(root, run_id)
        if manifest.get("cleanup_pending"):
            raise Conflict("Source cleanup is pending; retry deletion")
        source = experiments.experiment_directory(root, run_id) / "source.pdf"
        if not source.is_file():
            raise Missing("Original experiment PDF is no longer available")
        return FileResponse(
            source,
            media_type="application/pdf",
        )

    @router.post("/{run_id}/steps/{step}")
    async def execute(
        request: Request, run_id: str, step: str, background: BackgroundTasks
    ) -> RedirectResponse:
        """Save the submitted recipe and optionally run exactly one explicit step."""
        form = await checked_form(request, csrf_token)
        manifest = experiments.read_manifest(root, run_id)
        if manifest.get("legacy") or manifest.get("cleanup_pending"):
            raise Conflict("This source is read-only; create a new experiment or finish cleanup")
        action = str(form.get("action", "save"))
        if action not in {"run", "save"}:
            raise ValueError("Choose whether to save the recipe or run the step")
        recipe = save_step_configuration(step, form)
        if action == "run":
            attempt_id = experiments.prepare_attempt(root, run_id, step, recipe)
            background.add_task(experiments.execute_attempt, root, run_id, attempt_id)
        return RedirectResponse(f"/experiments/{run_id}#{step}", 303)

    @router.get("/{run_id}/attempts/{attempt_id}", response_class=HTMLResponse)
    def attempt(request: Request, run_id: str, attempt_id: str) -> HTMLResponse:
        """Show exact inputs, schema checks and inspectable execution records."""
        selected = selected_attempt(root, run_id, attempt_id)
        return render(
            request,
            "experiment_attempt.html",
            experiment=experiments.read_manifest(root, run_id),
            attempt=selected,
            trace=experiments.read_attempt_trace(root, run_id, attempt_id),
        )

    @router.post("/{run_id}/attempts/{attempt_id}/{action}")
    async def attempt_action(
        request: Request, run_id: str, attempt_id: str, action: str
    ) -> RedirectResponse:
        """Cancel, recover or review an attempt without approving generated knowledge."""
        form = await checked_form(request, csrf_token)
        if action == "cancel":
            experiments.request_cancel(root, run_id, attempt_id)
        elif action == "recover":
            experiments.recover_attempt(root, run_id, attempt_id)
        elif action == "review":
            ratings = {
                name: required_text(form, name) for name in ("usefulness", "faithfulness", "tone")
            }
            experiments.save_review(
                root,
                run_id,
                attempt_id,
                ratings,
                required_text(form, "comment", allow_empty=True),
                int(required_text(form, "expected_revision")),
            )
        else:
            raise ValueError("Unknown attempt action")
        return RedirectResponse(f"/experiments/{run_id}/attempts/{attempt_id}", 303)

    @router.get("/{run_id}/export")
    def export(run_id: str) -> JSONResponse:
        """Export only on explicit request, preserving a report outside experiment cleanup."""
        if experiments.read_manifest(root, run_id).get("cleanup_pending"):
            raise Conflict("Cleanup is pending; results may already be removed")
        return JSONResponse(
            experiments.export_experiment(root, run_id),
            headers={"Content-Disposition": f'attachment; filename="experiment-{run_id}.json"'},
        )

    @router.post("/{run_id}/delete")
    async def delete(request: Request, run_id: str) -> RedirectResponse:
        """Delete an idle owned experiment while leaving saved configuration intact."""
        await checked_form(request, csrf_token)
        experiments.delete_experiment(root, run_id)
        return RedirectResponse("/experiments", 303)

    return router
