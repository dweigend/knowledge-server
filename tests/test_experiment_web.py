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
    assert "validation error" in response.text
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
        {**previous.payload, "output_schema": "extraction.v3", "parameters": {}},
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
    assert attempt["recipe"]["payload"]["output_schema"] == "extraction.v4"
    assert "Ada Lovelace" in response.text
    assert "Run this step with literature matching" in response.text
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


def discovery_form(token):
    return {
        **step_form(token, "extract_text", "save"),
        "document_provider": "grobid",
        "service_url": "http://localhost:8070",
        "literature_provider": "discovery",
        "discovery_settings": "1",
        "discovery_providers": "dnb, openlibrary",
        "discovery_max_requests": "12",
        "discovery_max_requests_per_reference": "3",
        "discovery_max_model_calls": "0",
        "discovery_model_timeout_seconds": "30",
        "discovery_required_fields": "title, authors, year",
        "discovery_retry_generation": "2",
        "discovery_find_open_access": "on",
        "model": "test-search-model",
        "provider": "test-provider",
        "reasoning_effort": "high",
    }


def test_discovery_settings_save_and_survive_legacy_provider_selection(workbench):
    from knowledge.literature.reference_discovery_models import DiscoverySettings

    client, root, token = workbench
    run_id = source(client, token)
    url = f"/experiments/{run_id}/steps/extract_text"
    previous_default = get_default("recipe", "extract_text")
    response = client.post(url, data=discovery_form(token))
    assert response.status_code == 200, response.text
    saved = get_revision("recipe", "extract_text")
    recipe = Recipe.model_validate(saved.payload)
    settings = DiscoverySettings.model_validate(recipe.parameters["discovery"]).model_dump()
    assert settings == {
        "providers": ["dnb", "openlibrary"],
        "max_requests": 12,
        "max_requests_per_reference": 3,
        "max_model_calls": 0,
        "model_timeout_seconds": 30,
        "required_fields": ["title", "authors", "year"],
        "retry_generation": 2,
        "find_open_access": True,
    }
    assert recipe.output_schema == "extraction.v4"
    assert 'name="discovery_retry_generation" min="0" value="2"' in response.text
    form = {
        **step_form(token, "extract_text", "save"),
        "document_provider": "grobid",
        "service_url": "http://localhost:8070",
        "literature_provider": "crossref",
    }
    assert client.post(url, data=form).status_code == 200
    legacy_recipe = Recipe.model_validate(get_revision("recipe", "extract_text").payload)
    assert legacy_recipe.parameters["discovery"] == settings
    assert legacy_recipe.model.model == "test-search-model"
    assert legacy_recipe.model.provider == "test-provider"
    assert legacy_recipe.model.reasoning_effort == "high"
    assert get_default("recipe", "extract_text") == previous_default
    assert experiments.read_attempts(root, run_id) == []


@pytest.mark.parametrize(
    "invalid",
    [
        {"discovery_providers": "unknown"},
        {"discovery_max_requests": "-1"},
        {"discovery_retry_generation": "-1"},
        {"discovery_required_fields": "unknown"},
    ],
)
def test_invalid_discovery_settings_do_not_save_revisions(workbench, invalid):
    client, _, token = workbench
    run_id = source(client, token)
    before = get_revision("recipe", "extract_text")
    recipe = Recipe.model_validate(before.payload)
    prompt = get_revision("prompt", recipe.prompt_name)
    response = client.post(
        f"/experiments/{run_id}/steps/extract_text",
        data={**discovery_form(token), **invalid},
    )
    assert response.status_code == 422, response.text
    assert get_revision("recipe", "extract_text") == before
    assert get_revision("prompt", recipe.prompt_name) == prompt


def test_discovery_trace_and_historical_output_render_without_network(workbench, monkeypatch):
    from test_grobid import TEI

    from knowledge.literature.grobid_parser import parse_paper_tei

    client, root, token = workbench
    run_id = source(client, token)
    base = f"/experiments/{run_id}"
    assert client.post(f"{base}/steps/extract_text", data=step_form(token, "extract_text"))
    attempts = experiments.read_attempts(root, run_id)
    attempts[0]["output"]["paper"] = parse_paper_tei(TEI).model_dump()
    attempts[0]["output"].pop("discovery", None)
    monkeypatch.setattr(experiments, "read_attempts", lambda *args: attempts)

    def unexpected_request(*args, **kwargs):
        raise AssertionError("GET must not request literature or document services")

    monkeypatch.setattr("knowledge.literature.crossref_client.request_json", unexpected_request)
    monkeypatch.setattr("knowledge.literature.grobid_client.request_tei", unexpected_request)
    saved = get_revision("recipe", "extract_text")
    legacy = client.get(base)
    assert legacy.status_code == 200
    assert "A paper" in legacy.text
    assert "Discovery search trace" not in legacy.text
    attempts[0]["output"]["bibliography"] = {
        "original_count": 12,
        "detected_count": 19,
        "resulting_count": 19,
        "status": "needs_review",
        "model_status": "completed",
        "cache_reused": True,
        "unresolved_issues": ["Citation targets require review."],
    }
    attempts[0]["output"]["discovery"] = {
        "requests": 3,
        "cache_hits": 2,
        "model_calls": 0,
        "warnings": ["Request budget exhausted."],
        "searches": [
            {
                "reference_id": "b0",
                "trigger": "unmatched",
                "queries": [
                    {
                        "provider": "dnb",
                        "query": "A book",
                        "status": "success",
                        "cached": True,
                        "message": "No candidate found.",
                        "candidate_count": 0,
                    }
                ],
            }
        ],
    }
    page = client.get(base)
    assert page.status_code == 200, page.text
    assert "3 requests · 2 cache hits · 0 model calls" in page.text
    assert "Discovery search trace" in page.text
    assert "12 extracted · 19 detected in text · 19 retained" in page.text
    assert "Citation targets require review." in page.text
    assert "Request budget exhausted." in page.text
    assert "No candidate found." in page.text
    assert "dnb · success · cached" in page.text
    assert get_revision("recipe", "extract_text") == saved


@pytest.mark.parametrize(
    "address,visible",
    [
        ("https://example.org/open?article=1&format=pdf", True),
        ("http://example.org/open", True),
        ("javascript:alert(1)", False),
        ("data:text/html,unsafe", False),
        ("//example.org/open", False),
        (None, False),
    ],
)
def test_open_access_links_allow_only_explicit_web_urls(workbench, monkeypatch, address, visible):
    from knowledge.literature import literature_resolution
    from knowledge.literature.structured_paper_models import PaperReference

    client, _, _ = workbench
    reference = PaperReference(id="b0", title="An open work")
    record = literature_resolution.build_record(
        reference, literature_resolution.resolve_reference(reference, []), "source", "reference"
    )
    record.metadata.open_access_url = address
    record.metadata.open_access_pdf_url = address
    monkeypatch.setattr(
        "knowledge.experiments.experiment_literature_catalog.literature_catalog",
        lambda *args: [{"record": record, "documents": []}],
    )
    response = client.get("/experiments/literature")
    assert response.status_code == 200, response.text
    assert ("Open-access version ↗" in response.text) is visible
    assert ("Open-access PDF ↗" in response.text) is visible
    if visible:
        assert f'href="{address.replace("&", "&amp;")}"' in response.text
    elif address:
        assert address not in response.text
