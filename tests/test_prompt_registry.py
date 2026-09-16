import json
from pathlib import Path

import pytest

from knowledge.knowledge_domain.application_errors import Conflict, Missing
from knowledge.model_integration.prompt_registry import (
    Recipe,
    activate_revision,
    configuration_root,
    configuration_status,
    get_default,
    get_revision,
    operation_configuration,
    resolve_recipe,
    save_revision,
    seed_defaults,
)


def test_saved_recipe_does_not_activate_or_rewrite_pinned_prompt() -> None:
    seed_defaults()
    original, recipe, prompt, _ = resolve_recipe("segment_blocks")
    prompt_path = configuration_root() / "prompt" / "segment" / "1.json"
    original_bytes = prompt_path.read_bytes()
    changed = save_revision("prompt", "segment", {"text": "New instructions"}, 1)
    draft = save_revision(
        "recipe",
        "segment_blocks",
        recipe.model_copy(update={"prompt_revision": changed.revision}).model_dump(mode="json"),
        1,
    )
    assert get_default("recipe", "segment_blocks") == original
    assert resolve_recipe("segment_blocks")[2] == prompt
    activate_revision("recipe", "segment_blocks", draft.revision, 1)
    assert resolve_recipe("segment_blocks")[2] == changed
    assert resolve_recipe("segment_blocks", 1)[2] == prompt
    assert prompt_path.read_bytes() == original_bytes


def test_recipe_save_rejects_missing_prompt_and_partial_author_pin() -> None:
    seed_defaults()
    recipe = Recipe.model_validate(get_default("recipe", "draft_text").payload)
    with pytest.raises(Missing):
        save_revision(
            "recipe",
            "draft_text",
            {
                **recipe.model_dump(mode="json"),
                "prompt_revision": 99,
            },
            1,
        )
    with pytest.raises(ValueError, match="both name and revision"):
        save_revision(
            "recipe",
            "draft_text",
            {
                **recipe.model_dump(mode="json"),
                "author_rules_name": "david",
            },
            1,
        )
    assert get_revision("recipe", "draft_text").revision == 1


def test_author_rules_are_typed_and_pinned_independently_of_activation() -> None:
    seed_defaults()
    with pytest.raises(ValueError):
        save_revision("author_rules", "david", {"unknown": "unstructured"}, 0)
    rules = save_revision(
        "author_rules",
        "david",
        {
            "text": "Use short sentences.",
            "examples": ["A deliberately selected private example."],
        },
        0,
    )
    recipe = Recipe.model_validate(get_default("recipe", "draft_text").payload)
    draft = save_revision(
        "recipe",
        "draft_text",
        {
            **recipe.model_dump(mode="json"),
            "author_rules_name": "david",
            "author_rules_revision": rules.revision,
        },
        1,
    )
    assert resolve_recipe("draft_text", draft.revision)[3] == rules
    assert resolve_recipe("draft_text")[3] is None


def test_conflicts_preserve_saved_and_active_revisions() -> None:
    seed_defaults()
    original = get_default("prompt", "segment")
    saved = save_revision("prompt", "segment", {"text": "Draft"}, 1)
    with pytest.raises(Conflict):
        save_revision("prompt", "segment", {"text": "Stale save"}, 1)
    with pytest.raises(Conflict):
        activate_revision("prompt", "segment", saved.revision, 0)
    assert get_default("prompt", "segment") == original
    assert get_revision("prompt", "segment") == saved


def test_seed_defaults_never_reactivates_or_rewrites_saved_configuration() -> None:
    seed_defaults()
    saved = save_revision("prompt", "segment", {"text": "My active instructions"}, 1)
    activate_revision("prompt", "segment", 2, 1)
    seed_defaults()
    assert get_default("prompt", "segment") == saved
    assert resolve_recipe("segment_blocks")[1].prompt_revision == 1
    status = next(row for row in configuration_status("prompt") if row["name"] == "segment")
    assert status["revision"] == status["active_revision"] == 2


def test_resolution_rejects_changed_referenced_content() -> None:
    seed_defaults()
    prompt_path = configuration_root() / "prompt" / "segment" / "1.json"
    document = json.loads(prompt_path.read_text())
    document["payload"]["text"] = "Changed outside registry"
    prompt_path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="hash"):
        resolve_recipe("segment_blocks")
    with pytest.raises(ValueError, match="hash"):
        get_default("recipe", "segment_blocks")


def test_recipe_contract_rejects_unknown_step_and_unsupported_tools() -> None:
    seed_defaults()
    original = get_default("recipe", "segment_blocks").payload
    for changes in ({"step": "execute_shell"}, {"model": {"allowed_tools": ["shell"]}}):
        with pytest.raises(ValueError):
            save_revision("recipe", "segment_blocks", {**original, **changes}, 1)


def test_operation_configuration_tracks_recipe_activation_not_saved_draft() -> None:
    instructions, model = operation_configuration("formulate_claims")
    original = get_default("recipe", "formulate_claims")
    changed = save_revision("prompt", "import", {"text": "Reviewed new instructions"}, 1)
    updated = save_revision(
        "recipe",
        "formulate_claims",
        {
            **original.payload,
            "prompt_revision": changed.revision,
            "model": {"model": "alternative", "provider": "custom"},
        },
        1,
    )
    assert operation_configuration("formulate_claims") == (instructions, model)
    activate_revision("recipe", "formulate_claims", updated.revision, original.revision)
    active_instructions, active_model = operation_configuration("formulate_claims")
    assert active_instructions == "Reviewed new instructions"
    assert active_model.model == "alternative"
    assert active_model.provider == "custom"


def test_secondary_operation_prompt_is_a_validated_immutable_pin() -> None:
    instructions, _ = operation_configuration("propose_changes", secondary_prompt=True)
    save_revision("prompt", "consolidate", {"text": "Unactivated new prompt"}, 1)
    assert operation_configuration("propose_changes", secondary_prompt=True)[0] == instructions
    original = get_default("recipe", "propose_changes")
    with pytest.raises(Missing):
        save_revision(
            "recipe",
            "propose_changes",
            {
                **original.payload,
                "parameters": {"note_prompt_name": "consolidate", "note_prompt_revision": 999},
            },
            1,
        )


def test_main_import_uses_activated_recipe_at_the_provider_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge.source_workflows.article_claim_extraction import extract_document

    requests = []

    def respond(arguments: list[str], **kwargs: object) -> None:
        request = json.loads(Path(arguments[-2]).read_text())
        requests.append(request)
        response = {
            "bibliography": {
                "title": "Fixture",
                "authors": [],
                "year": "2026",
                "doi": "",
                "url": "",
            },
            "claims": [],
            "study_group": "fixture",
            "overlap": "unknown",
            "warnings": [],
        }
        Path(arguments[-1]).write_text(
            json.dumps(
                {
                    "execution": "simulated",
                    "response": json.dumps(response),
                }
            )
        )

    monkeypatch.setattr("knowledge.model_integration.structured_generation.subprocess.run", respond)
    extract_document(["A manually checked fixture passage."], tmp_path / "first")
    original = get_default("recipe", "formulate_claims")
    prompt = save_revision("prompt", "import", {"text": "Activated import instructions"}, 1)
    saved = save_revision(
        "recipe",
        "formulate_claims",
        {
            **original.payload,
            "prompt_revision": prompt.revision,
            "model": {"model": "chosen-model", "provider": "chosen-provider"},
        },
        1,
    )
    activate_revision("recipe", "formulate_claims", saved.revision, 1)
    extract_document(["A manually checked fixture passage."], tmp_path / "second")
    assert requests[0]["instructions"] != requests[1]["instructions"]
    assert requests[1]["instructions"] == "Activated import instructions"
    configuration = json.loads(requests[1]["configuration"])
    assert configuration["model"] == "chosen-model"
    assert configuration["provider"] == "chosen-provider"
