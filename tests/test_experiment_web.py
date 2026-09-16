import json
import re

import pytest
from fastapi.testclient import TestClient
from test_experimentation import fixture_pdf

import knowledge.experiments.experiment_runner as experiments
from knowledge.model_integration.prompt_registry import Recipe, get_default, get_revision
from knowledge.runtime_support.environment_settings import Settings
from knowledge.web_interface.fastapi_app import create_app


@pytest.fixture
def workbench(tmp_path, monkeypatch):
    def unexpected_model(*args, **kwargs):
        raise AssertionError("Reading or deterministic operations must not request a model")

    monkeypatch.setattr(
        "knowledge.model_integration.structured_generation.run_hermes", unexpected_model
    )
    root = tmp_path / "archive"
    with TestClient(create_app(Settings(database_url="unused", archive_root=root))) as client:
        page = client.get("/experiments")
        match = re.search(r'name="csrf" value="([^"]+)"', page.text)
        assert match
        token = match[1]
        yield client, root, token


pytestmark = pytest.mark.usefixtures("poppler_extraction")


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


def test_manual_pdf_blocks_history_comparison_and_cleanup(workbench):
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
        {"reasoning_effort": "unsupported"},
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


def test_grobid_form_upgrades_recipe_and_renders_bibliography(workbench, monkeypatch):
    from test_grobid import TEI

    from knowledge.model_integration.prompt_registry import save_revision

    client, root, token = workbench
    run_id = source(client, token)
    previous = get_revision("recipe", "extract_text")
    save_revision(
        "recipe",
        "extract_text",
        {**previous.payload, "output_schema": "extraction.v1", "parameters": {}},
        previous.revision,
    )
    monkeypatch.setattr(
        "knowledge.literature.grobid_client.request_tei",
        lambda *args: TEI.encode() + b"\n200",
    )
    response = client.post(
        f"/experiments/{run_id}/steps/extract_text",
        data={
            **step_form(token, "extract_text"),
            "document_provider": "grobid",
            "service_url": "http://localhost:8070",
            "literature_provider": "none",
        },
    )
    assert response.status_code == 200, response.text
    attempt = experiments.read_attempts(root, run_id)[0]
    assert attempt["status"] == "completed", attempt["error"]
    assert attempt["recipe"]["payload"]["output_schema"] == "extraction.v3"
    assert "Ada Lovelace" in response.text
    assert "Run this step with Crossref matching" in response.text
    assert "<h1>A paper</h1>" in response.text
    assert "Original page text" not in response.text
    assert "PDF page 1" not in response.text
    assert get_default("recipe", "extract_text") == previous


def test_source_records_link_context_and_export_network_without_queries_on_read(
    workbench, monkeypatch
):
    from test_grobid import TEI

    from knowledge.literature.literature_models import Candidate, LiteratureMetadata

    client, root, token = workbench
    run_id = source(client, token)
    monkeypatch.setattr(
        "knowledge.literature.grobid_client.request_tei",
        lambda *args: TEI.encode() + b"\n200",
    )
    requests = []

    def lookup(reference, *args):
        requests.append(reference.title)
        if reference.title != "A paper":
            return []
        return [
            Candidate(
                metadata=LiteratureMetadata(
                    title="A paper", authors=["Ada Lovelace"], year="2024", doi="10.1234/paper"
                ),
                provider="crossref",
                provider_id="10.1234/paper",
                method="bibliographic",
            )
        ]

    monkeypatch.setattr("knowledge.literature.literature_resolution.lookup_crossref", lookup)
    response = client.post(
        f"/experiments/{run_id}/steps/extract_text",
        data={
            **step_form(token, "extract_text"),
            "document_provider": "grobid",
            "service_url": "http://localhost:8070",
            "literature_provider": "crossref",
        },
    )
    assert response.status_code == 200, response.text
    attempt = experiments.read_attempts(root, run_id)[0]
    assert attempt["status"] == "completed", attempt["error"]
    assert "Cited sources" in response.text
    assert "Text before [1] after." in response.text
    assert "PDF page 1" not in response.text
    request_count = len(requests)
    assert request_count > 0
    for url in ("/experiments/literature", "/experiments/literature?work_id=doi:10.1234/paper"):
        page = client.get(url)
        assert page.status_code == 200
        assert "Ada Lovelace" in page.text
    exported = client.get("/experiments/literature/export").json()
    assert exported["schema"] == "literature-network.v1"
    works = exported["works"]
    assert any(work["record"]["id"] == "doi:10.1234/paper" for work in works)
    occurrences = [
        o for work in works for doc in work["documents"] for o in doc["record"]["occurrences"]
    ]
    assert len(occurrences) == 2
    assert {occurrence["section"] for occurrence in occurrences} == {"Introduction", "Details"}
    assert len(requests) == request_count
