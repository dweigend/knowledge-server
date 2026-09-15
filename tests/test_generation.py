import json
from pathlib import Path

from knowledge.contracts import Contract
from knowledge.generation import generate


class Proposal(Contract):
    quote: str


def test_cached_schema_valid_output_must_pass_domain_validation(tmp_path, monkeypatch):
    calls = []

    def respond(arguments, **kwargs):
        calls.append(arguments)
        quote = "fabricated" if len(calls) == 1 else "exact source"
        Path(arguments[-1]).write_text(json.dumps({"response": json.dumps({"quote": quote})}))

    monkeypatch.setattr("knowledge.generation.subprocess.run", respond)
    first = generate("Instructions", "Source", Proposal, tmp_path)
    assert first.quote == "fabricated"

    def validate(proposal):
        if proposal.quote != "exact source":
            raise ValueError("Quote not in source")

    repaired = generate("Instructions", "Source", Proposal, tmp_path, validate=validate)
    assert repaired.quote == "exact source"
    assert len(calls) == 2


def test_json_syntax_repair_excludes_large_source_context(tmp_path, monkeypatch):
    requests = []

    def respond(arguments, **kwargs):
        requests.append(json.loads(Path(arguments[-2]).read_text()))
        response = '{"quote": "exact",}' if len(requests) == 1 else '{"quote": "exact"}'
        Path(arguments[-1]).write_text(json.dumps({"response": response}))

    monkeypatch.setattr("knowledge.generation.subprocess.run", respond)
    proposal = generate("Extract JSON", "LARGE_SOURCE_CONTEXT", Proposal, tmp_path)
    assert proposal.quote == "exact"
    assert len(requests) == 2
    assert "LARGE_SOURCE_CONTEXT" in requests[0]["input"]
    assert "LARGE_SOURCE_CONTEXT" not in requests[1]["input"]
    assert "Validation errors" in requests[1]["input"]


def test_configuration_variants_do_not_share_model_responses(tmp_path, monkeypatch):
    from knowledge.generation import ModelConfiguration

    requests = []

    def respond(arguments, **kwargs):
        request = json.loads(Path(arguments[-2]).read_text())
        requests.append(json.loads(request["configuration"]))
        Path(arguments[-1]).write_text(json.dumps({"response": '{"quote": "exact"}'}))

    monkeypatch.setattr("knowledge.generation.subprocess.run", respond)
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


def test_single_attempt_does_not_run_repair(tmp_path, monkeypatch):
    import pytest

    from knowledge.generation import ModelConfiguration

    calls = []

    def respond(arguments, **kwargs):
        calls.append(arguments)
        assert kwargs["timeout"] == 12
        Path(arguments[-1]).write_text(json.dumps({"response": "invalid"}))

    monkeypatch.setattr("knowledge.generation.subprocess.run", respond)
    with pytest.raises(ValueError, match="failed contract"):
        generate(
            "Instructions",
            "Source",
            Proposal,
            tmp_path,
            configuration=ModelConfiguration(max_attempts=1, timeout_seconds=12),
        )
    assert len(calls) == 1


def test_unsupported_model_capabilities_are_rejected():
    import pytest

    from knowledge.generation import ModelConfiguration

    for configuration in [
        {"allowed_tools": ["shell"]},
        {"cost_limit_usd": 1},
        {"max_attempts": 3},
        {"timeout_seconds": 0},
    ]:
        with pytest.raises(ValueError):
            ModelConfiguration.model_validate(configuration)


def test_cancelled_generation_does_not_create_request(tmp_path):
    import pytest

    with pytest.raises(InterruptedError, match="cancelled"):
        generate("Instructions", "Source", Proposal, tmp_path, cancelled=lambda: True)
    assert list(tmp_path.iterdir()) == []


def test_running_hermes_is_terminated_on_cancellation():
    import subprocess
    from unittest.mock import Mock

    import pytest

    from knowledge.generation import wait_for_hermes

    process = Mock(spec=subprocess.Popen)
    process.poll.return_value = None
    with pytest.raises(InterruptedError):
        wait_for_hermes(process, 30, lambda: True)
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=2)
