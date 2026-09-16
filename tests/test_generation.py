import json
from pathlib import Path
from typing import Never

import pytest

from knowledge.knowledge_domain.knowledge_record_models import Contract
from knowledge.model_integration.structured_generation import generate


class Proposal(Contract):
    quote: str


def test_cached_schema_valid_output_must_pass_domain_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def respond(arguments: list[str], **kwargs: object) -> None:
        calls.append(arguments)
        quote = "fabricated" if len(calls) == 1 else "exact source"
        Path(arguments[-1]).write_text(json.dumps({"response": json.dumps({"quote": quote})}))

    monkeypatch.setattr("knowledge.model_integration.structured_generation.subprocess.run", respond)
    first = generate("Instructions", "Source", Proposal, tmp_path)
    assert first.quote == "fabricated"

    def validate(proposal: Proposal) -> None:
        if proposal.quote != "exact source":
            raise ValueError("Quote not in source")

    repaired = generate("Instructions", "Source", Proposal, tmp_path, validate=validate)
    assert repaired.quote == "exact source"
    assert len(calls) == 2


def test_json_syntax_repair_excludes_large_source_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = []

    def respond(arguments: list[str], **kwargs: object) -> None:
        requests.append(json.loads(Path(arguments[-2]).read_text()))
        response = '{"quote": "exact",}' if len(requests) == 1 else '{"quote": "exact"}'
        Path(arguments[-1]).write_text(json.dumps({"response": response}))

    monkeypatch.setattr("knowledge.model_integration.structured_generation.subprocess.run", respond)
    proposal = generate("Extract JSON", "LARGE_SOURCE_CONTEXT", Proposal, tmp_path)
    assert proposal.quote == "exact"
    assert len(requests) == 2
    assert "LARGE_SOURCE_CONTEXT" in requests[0]["input"]
    assert "LARGE_SOURCE_CONTEXT" not in requests[1]["input"]
    assert "Validation errors" in requests[1]["input"]


def test_configuration_variants_do_not_share_model_responses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge.model_integration.structured_generation import ModelConfiguration

    requests = []

    def respond(arguments: list[str], **kwargs: object) -> None:
        request = json.loads(Path(arguments[-2]).read_text())
        requests.append(json.loads(request["configuration"]))
        Path(arguments[-1]).write_text(json.dumps({"response": '{"quote": "exact"}'}))

    monkeypatch.setattr("knowledge.model_integration.structured_generation.subprocess.run", respond)
    generate("Instructions", "Source", Proposal, tmp_path)
    generate("Instructions", "Source", Proposal, tmp_path)
    generate(
        "Instructions",
        "Source",
        Proposal,
        tmp_path,
        configuration=ModelConfiguration(model="alternative", provider="custom"),
    )
    assert [request["model"] for request in requests] == ["gpt-5.6-luna", "alternative"]
    assert [request["provider"] for request in requests] == ["openai-codex", "custom"]
    assert [request["reasoning_effort"] for request in requests] == ["max", "max"]


def test_single_attempt_does_not_run_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pytest

    from knowledge.model_integration.structured_generation import ModelConfiguration

    calls = []

    def respond(arguments: list[str], **kwargs: object) -> None:
        calls.append(arguments)
        assert kwargs["timeout"] == 12
        Path(arguments[-1]).write_text(json.dumps({"response": "invalid"}))

    monkeypatch.setattr("knowledge.model_integration.structured_generation.subprocess.run", respond)
    with pytest.raises(ValueError, match="failed contract"):
        generate(
            "Instructions",
            "Source",
            Proposal,
            tmp_path,
            configuration=ModelConfiguration(max_attempts=1, timeout_seconds=12),
        )
    assert len(calls) == 1


def test_unsupported_model_capabilities_are_rejected() -> None:
    import pytest

    from knowledge.model_integration.structured_generation import ModelConfiguration

    for configuration in [
        {"allowed_tools": ["shell"]},
        {"cost_limit_usd": 1},
        {"reasoning_effort": "unsupported"},
        {"max_attempts": 3},
        {"timeout_seconds": 0},
    ]:
        with pytest.raises(ValueError):
            ModelConfiguration.model_validate(configuration)


def test_cancelled_generation_does_not_create_request(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(InterruptedError, match="cancelled"):
        generate("Instructions", "Source", Proposal, tmp_path, cancelled=lambda: True)
    assert list(tmp_path.iterdir()) == []


def test_running_hermes_is_terminated_on_cancellation() -> None:
    import subprocess
    from unittest.mock import Mock

    import pytest

    from knowledge.model_integration.structured_generation import wait_for_hermes

    process = Mock(spec=subprocess.Popen)
    process.poll.return_value = None
    with pytest.raises(InterruptedError):
        wait_for_hermes(process, 30, lambda: True)
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=2)


def test_provider_failure_records_inspectable_event_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    import pytest

    def fail(arguments: list[str], **kwargs: object) -> Never:
        raise subprocess.CalledProcessError(1, arguments, stderr="SECRET_PROVIDER_TOKEN")

    monkeypatch.setattr("knowledge.model_integration.structured_generation.subprocess.run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        generate("Instructions", "Source", Proposal, tmp_path)
    events = [
        json.loads(line)
        for path in tmp_path.glob("*/events.jsonl")
        for line in path.read_text().splitlines()
    ]
    failure = next(event for event in events if event["event"] == "model_attempt_failed")
    assert failure["error_type"] == "CalledProcessError"
    assert failure["status"] == "failed"
    assert failure["elapsed_seconds"] >= 0
    assert "SECRET_PROVIDER_TOKEN" not in json.dumps(events)


def test_reused_response_preserves_files_and_records_effective_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(arguments: list[str], **kwargs: object) -> None:
        Path(arguments[-1]).write_text(
            json.dumps(
                {
                    "model": "actual-model",
                    "provider": "actual-provider",
                    "execution": "simulated",
                    "response": '{"quote": "exact"}',
                }
            )
        )

    monkeypatch.setattr("knowledge.model_integration.structured_generation.subprocess.run", respond)
    generate("Instructions", "Source", Proposal, tmp_path)
    responses = {path: path.read_bytes() for path in tmp_path.glob("*/response-*.json")}
    generate("Instructions", "Source", Proposal, tmp_path)
    assert {path: path.read_bytes() for path in responses} == responses
    events = [
        json.loads(line)
        for path in tmp_path.glob("*/events.jsonl")
        for line in path.read_text().splitlines()
    ]
    result = next(event for event in events if event["event"] == "model_response")
    assert result["model"] == "actual-model"
    assert result["provider"] == "actual-provider"
    assert result["response_origin"] == "simulated"
    assert events[-1]["event"] == "model_cache_reused"


def test_bridge_does_not_report_requested_model_as_verified_runtime() -> None:
    from knowledge.model_integration.hermes_bridge import run_request

    class Agent:
        session_id = "test-session"

        def run_conversation(self, *, user_message: str, system_message: str) -> dict[str, str]:
            return {"final_response": "{}"}

        def close(self) -> None:
            pass

    agent = Agent()
    response = run_request(agent, {"input": "fixture", "instructions": "fixture"}, "a", "b")
    assert response.model is None
    assert response.provider is None
    assert response.requested_model == "a"
    assert response.requested_provider == "b"


def test_bridge_passes_pinned_reasoning_effort_to_hermes(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from types import SimpleNamespace

    from knowledge.model_integration.hermes_bridge import create_agent

    received = {}

    class Agent:
        def __init__(self, **settings: object) -> None:
            received.update(settings)

    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.runtime_provider",
        SimpleNamespace(
            resolve_runtime_provider=lambda **kwargs: {
                "provider": kwargs["requested"],
                "api_mode": "responses",
                "api_key": None,
                "base_url": None,
            }
        ),
    )
    monkeypatch.setitem(sys.modules, "run_agent", SimpleNamespace(AIAgent=Agent))

    create_agent("gpt-5.6-luna", "openai-codex", reasoning_effort="max")

    assert received["reasoning_config"] == {"effort": "max"}


def test_standalone_bridge_validates_shared_configuration_before_loading_hermes(
    tmp_path: Path,
) -> None:
    import subprocess
    import sys

    from knowledge.model_integration import hermes_bridge

    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "input": "fixture",
                "instructions": "fixture",
                "configuration": json.dumps({"allowed_tools": ["shell"]}),
            }
        )
    )
    result = subprocess.run(
        [
            sys.executable,
            str(Path(hermes_bridge.__file__)),
            str(request),
            str(tmp_path / "response.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "does not support tool execution" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert not (tmp_path / "response.json").exists()
