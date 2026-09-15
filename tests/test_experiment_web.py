import json
import re

import pytest
from fastapi.testclient import TestClient
from test_experimentation import fixture_pdf

from knowledge import experimentation as experiments
from knowledge.config import Settings
from knowledge.prompt_registry import Recipe, get_default, get_revision
from knowledge.web import create_app


@pytest.fixture
def workbench(tmp_path, monkeypatch):
    def unexpected_model(*args, **kwargs):
        raise AssertionError("Reading or deterministic operations must not request a model")

    monkeypatch.setattr("knowledge.generation.run_hermes", unexpected_model)
    root = tmp_path / "archive"
    with TestClient(create_app(Settings("unused", root))) as client:
        page = client.get("/experiments")
        match = re.search(r'name="csrf" value="([^"]+)"', page.text)
        assert match
        token = match[1]
        yield client, root, token


def source(client, token):
    response = client.post(
        "/experiments",
        data={"csrf": token},
        files={"sources": ("independent.pdf", fixture_pdf(), "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response.headers["location"].rsplit("/", 1)[1]


def step_form(token, step, action="run"):
    saved = get_revision("recipe", step)
    recipe = Recipe.model_validate(saved.payload)
    prompt = get_revision("prompt", recipe.prompt_name)
    parameters = recipe.parameters
    if step == "segment_blocks":
        parameters = {"mode": "paragraphs", "max_characters": 2000}
    return {
        "csrf": token,
        "expected_revision": str(saved.revision),
        "prompt_revision": str(prompt.revision),
        "instructions": prompt.payload["text"],
        "parameters": json.dumps(parameters),
        "action": action,
    }


def test_pages_render_without_template_syntax_or_model_requests(workbench):
    client, _, token = workbench
    for url in ("/experiments", "/experiments/compare", "/experiments/settings"):
        response = client.get(url)
        assert response.status_code == 200, response.text
        assert "{%" not in response.text
        assert "{{" not in response.text
    assert client.get("/static/app.css").status_code == 200
    assert token


def test_manual_pdf_blocks_history_comparison_review_and_cleanup(workbench):
    client, root, token = workbench
    run_id = source(client, token)
    base = f"/experiments/{run_id}"
    assert experiments.read_attempts(root, run_id) == []
    for step in ("extract_text", "segment_blocks"):
        response = client.post(f"{base}/steps/{step}", data=step_form(token, step))
        assert response.status_code == 200, response.text
    attempts = experiments.read_attempts(root, run_id)
    assert len(attempts) == 2
    assert all(a["status"] == "completed" for a in attempts)
    assert "First observation." in client.get(base).text
    blocks = attempts[-1]
    inspect = f"{base}/attempts/{blocks['id']}"
    assert client.get(inspect).status_code == 200
    assert client.get("/experiments/compare?step=segment_blocks").status_code == 200
    reviewed = client.post(
        f"{inspect}/review",
        data={
            "csrf": token,
            "expected_revision": "0",
            "usefulness": "good",
            "faithfulness": "good",
            "tone": "not_applicable",
            "comment": "Independently checked exact fixture text.",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    report = client.get(f"{base}/export").json()
    assert report
    saved_before = get_revision("recipe", "segment_blocks")
    assert client.post(f"{base}/delete", data={"csrf": token}).status_code == 200
    assert get_revision("recipe", "segment_blocks") == saved_before
    assert not (root.parent / "experiments" / run_id).exists()


def test_mutations_require_csrf_and_dependency_failure_is_inspectable(workbench):
    client, root, token = workbench
    run_id = source(client, token)
    base = f"/experiments/{run_id}"
    rejected = client.post(f"{base}/delete", headers={"Origin": "https://example.org"})
    assert rejected.status_code == 403
    assert experiments.read_manifest(root, run_id)
    response = client.post(f"{base}/steps/segment_blocks", data=step_form(token, "segment_blocks"))
    assert response.status_code == 422
    assert "Run extract_text" in response.text
    assert experiments.read_attempts(root, run_id) == []


def test_recipe_save_does_not_run_or_activate_and_stale_form_conflicts(workbench):
    client, root, token = workbench
    run_id = source(client, token)
    previous = get_default("recipe", "extract_text")
    form = step_form(token, "extract_text", "save")
    url = f"/experiments/{run_id}/steps/extract_text"
    assert client.post(url, data=form).status_code == 200
    assert get_default("recipe", "extract_text") == previous
    assert experiments.read_attempts(root, run_id) == []
    assert client.post(url, data=form).status_code == 409


def test_duplicate_comparison_source_cannot_leave_orphan_queued_attempt(workbench):
    client, root, token = workbench
    run_id = source(client, token)
    base = f"/experiments/{run_id}"
    for _ in range(2):
        client.post(f"{base}/steps/extract_text", data=step_form(token, "extract_text"))
    attempts = experiments.read_attempts(root, run_id)
    response = client.post(
        "/experiments/compare",
        data={
            "csrf": token,
            "attempts": [f"{run_id}:{a['id']}" for a in attempts],
            "recipe_name": "extract_text",
            "recipe_revision": get_revision("recipe", "extract_text").revision,
        },
    )
    assert response.status_code == 422
    assert len(experiments.read_attempts(root, run_id)) == 2


def test_invalid_second_upload_does_not_create_the_first_source(workbench):
    client, root, token = workbench
    response = client.post(
        "/experiments",
        data={"csrf": token},
        files=[
            ("sources", ("valid.pdf", fixture_pdf(), "application/pdf")),
            ("sources", ("broken.pdf", b"This is not PDF content", "application/pdf")),
        ],
    )
    assert response.status_code == 422
    assert "PDF header" in response.text
    assert experiments.list_experiments(root) == []


@pytest.mark.parametrize("knowledge", ["null", "{}", '"not records"'])
def test_invalid_knowledge_snapshot_shape_does_not_create_sources(workbench, knowledge):
    client, root, token = workbench
    response = client.post(
        "/experiments",
        data={"csrf": token, "knowledge": knowledge},
        files={"sources": ("valid.pdf", fixture_pdf(), "application/pdf")},
    )
    assert response.status_code == 422
    assert "JSON list" in response.text
    assert experiments.list_experiments(root) == []


@pytest.mark.parametrize(
    "route,fields,missing",
    [
        ("/settings/activate", {}, "kind"),
        ("/settings/activate", {"kind": "recipe"}, "name"),
        ("/settings/rules", {}, "name"),
        ("/settings/rules", {"name": "author"}, "text"),
        ("/compare", {"attempts": "placeholder:placeholder"}, "recipe_name"),
    ],
)
def test_missing_configuration_fields_return_validation_errors(workbench, route, fields, missing):
    client, _, token = workbench
    response = client.post(f"/experiments{route}", data={"csrf": token, **fields})
    assert response.status_code == 422, response.text
    assert f"Missing required form field: {missing}" in response.text


@pytest.mark.parametrize("missing", ["expected_revision", "prompt_revision", "instructions"])
def test_missing_step_fields_do_not_save_any_configuration(workbench, missing):
    client, _, token = workbench
    run_id = source(client, token)
    before = get_revision("recipe", "extract_text")
    recipe = Recipe.model_validate(before.payload)
    prompt_before = get_revision("prompt", recipe.prompt_name)
    form = step_form(token, "extract_text", "save")
    form.pop(missing)
    response = client.post(f"/experiments/{run_id}/steps/extract_text", data=form)
    assert response.status_code == 422
    assert f"Missing required form field: {missing}" in response.text
    assert get_revision("recipe", "extract_text") == before
    assert get_revision("prompt", recipe.prompt_name) == prompt_before


@pytest.mark.parametrize(
    "invalid",
    [
        {"timeout_seconds": "0"},
        {"max_attempts": "7"},
        {"allowed_tools": '["unsupported"]'},
        {"parameters": "{"},
        {"parameters": "[]"},
        {"parameters": '{"unknown_setting": true}'},
        {"author_rules_name": "missing-rules"},
        {"author_rules_name": "missing-rules", "author_rules_revision": "1"},
        {"action": "unexpected"},
    ],
)
def test_invalid_model_recipe_or_parameters_do_not_leave_prompt_drafts(workbench, invalid):
    client, _, token = workbench
    run_id = source(client, token)
    before = get_revision("recipe", "extract_text")
    recipe = Recipe.model_validate(before.payload)
    prompt_before = get_revision("prompt", recipe.prompt_name)
    form = {
        **step_form(token, "extract_text", "save"),
        "instructions": "A new unsaved instruction",
        **invalid,
    }
    response = client.post(f"/experiments/{run_id}/steps/extract_text", data=form)
    assert response.status_code in {404, 422}, response.text
    assert get_revision("recipe", "extract_text") == before
    assert get_revision("prompt", recipe.prompt_name) == prompt_before


def test_missing_review_fields_return_validation_error(workbench):
    client, _, token = workbench
    run_id = source(client, token)
    response = client.post(
        f"/experiments/{run_id}/attempts/{'0' * 32}/review", data={"csrf": token}
    )
    assert response.status_code == 422
    assert "Missing required form field: usefulness" in response.text


def test_legacy_source_remains_readable_and_does_not_break_comparison(workbench):
    client, root, token = workbench
    run_id = source(client, token)
    path = experiments.experiment_directory(root, run_id) / "manifest.json"
    legacy = json.loads(path.read_text())
    legacy.pop("version")
    path.write_text(json.dumps(legacy))
    assert client.get(f"/experiments/{run_id}").status_code == 200
    assert client.get("/experiments/compare").status_code == 200
    assert client.get(f"/experiments/{run_id}/export").status_code == 200
    before = get_revision("recipe", "extract_text")
    response = client.post(
        f"/experiments/{run_id}/steps/extract_text", data=step_form(token, "extract_text")
    )
    assert response.status_code == 409
    assert get_revision("recipe", "extract_text") == before


def test_partial_cleanup_remains_visible_and_retriable_in_dashboard(workbench, monkeypatch):
    client, root, token = workbench
    run_id = source(client, token)
    with monkeypatch.context() as failed_filesystem:

        def fail_after_manifest_removed(path):
            (path / "manifest.json").unlink()
            raise PermissionError("simulated partial filesystem deletion")

        failed_filesystem.setattr(
            "knowledge.experimentation.shutil.rmtree", fail_after_manifest_removed
        )
        response = client.post(f"/experiments/{run_id}/delete", data={"csrf": token})
        assert response.status_code == 422
    assert client.get(f"/experiments/{run_id}").status_code == 200
    assert client.get("/experiments/compare").status_code == 200
    assert client.get(f"/experiments/{run_id}/pdf").status_code == 409
    assert client.get(f"/experiments/{run_id}/export").status_code == 409
    assert client.post(f"/experiments/{run_id}/delete", data={"csrf": token}).status_code == 200
    assert experiments.list_experiments(root) == []
