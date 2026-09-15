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
