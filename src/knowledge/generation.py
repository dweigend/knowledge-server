"""Bounded Hermes subprocess adapter with cached, schema-validated proposals."""

import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from time import monotonic

from pydantic import ValidationError

from knowledge.contracts import Contract
from knowledge.run_log import record_event

HERMES_PYTHON = Path(
    os.environ.get(
        "KNOWLEDGE_HERMES_PYTHON", str(Path.home() / ".hermes/hermes-agent/venv/bin/python")
    )
)


def generate[T: Contract](
    instructions: str,
    packet: str,
    contract: type[T],
    output_directory: Path,
    validate: Callable[[T], None] | None = None,
) -> T:
    """Reuse a validated proposal or request at most two schema-checked attempts."""
    schema = json.dumps(contract.model_json_schema(), ensure_ascii=False)
    request = {"instructions": instructions, "input": f"SCHEMA:\n{schema}\n\nINPUT:\n{packet}"}
    identity = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    directory = output_directory / identity
    directory.mkdir(parents=True, exist_ok=True)
    accepted = directory / "validated.json"
    cached = load_cached_proposal(accepted, contract, validate)
    if cached is not None:
        return cached
    return generate_attempts(request, directory, contract, validate)


def generate_attempts[T: Contract](
    request: dict[str, str],
    directory: Path,
    contract: type[T],
    validate: Callable[[T], None] | None,
) -> T:
    """Try the initial request and one repair, preserving every response for inspection."""
    accepted = directory / "validated.json"
    for attempt in range(2):
        started = monotonic()
        response = request_response(request, directory, attempt)
        proposal = validate_response(response, request, contract, validate)
        record_event(
            directory,
            "model_attempt",
            attempt=attempt + 1,
            status="rejected" if proposal is None else "validated",
            elapsed_seconds=round(monotonic() - started, 2),
            contract=contract.__name__,
        )
        if proposal is None:
            continue
        accepted.write_text(proposal.model_dump_json(indent=2))
        return proposal
    raise ValueError(f"Model output failed contract validation; inspect {directory}")


def validate_response[T: Contract](
    response: str,
    request: dict[str, str],
    contract: type[T],
    validate: Callable[[T], None] | None,
) -> T | None:
    """Validate a response or add its errors to the request for the repair attempt."""
    try:
        proposal = contract.model_validate_json(response)
        validate_proposal(proposal, validate)
        return proposal
    except ValueError as error:
        if isinstance(error, ValidationError) and error.errors()[0]["type"] == "json_invalid":
            request["input"] = "SCHEMA:\n" + json.dumps(contract.model_json_schema())
        request["input"] += (
            f"\nPrevious invalid output:\n{response}\nValidation errors:\n{error}\n"
            "Return complete, indented, syntactically valid JSON. No dangling quotes or commas. "
            "Preserve valid content. Use verbatim quotes from the supplied pages; "
            "omit invalid relations."
        )
        return None


def validate_proposal[T: Contract](proposal: T, validate: Callable[[T], None] | None) -> None:
    """Apply optional domain checks after structural contract validation."""
    if validate is None:
        return
    validate(proposal)


def load_cached_proposal[T: Contract](
    accepted: Path,
    contract: type[T],
    validate: Callable[[T], None] | None,
) -> T | None:
    """Recheck domain validity; an outdated cached proposal triggers regeneration."""
    if not accepted.exists():
        return None
    cached = contract.model_validate_json(accepted.read_text())
    try:
        validate_proposal(cached, validate)
    except ValueError:
        return None
    return cached


def run_hermes(request_path: Path, response_path: Path, log_path: Path) -> None:
    """Run the installed Hermes adapter with a timeout and a private diagnostic log."""
    with log_path.open("w") as log:
        subprocess.run(
            [
                str(HERMES_PYTHON),
                str(Path(__file__).with_name("hermes_bridge.py")),
                str(request_path),
                str(response_path),
            ],
            stdout=log,
            stderr=log,
            check=True,
            timeout=240,
        )


def request_response(request: dict[str, str], directory: Path, attempt: int) -> str:
    """Reuse recorded responses and preserve changed repair requests separately."""
    request_path = directory / f"request-{attempt}.json"
    response_path = directory / f"response-{attempt}.json"
    if request_path.exists() and json.loads(request_path.read_text()) != request:
        suffix = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16]
        request_path = directory / f"request-{attempt}-{suffix}.json"
        response_path = directory / f"response-{attempt}-{suffix}.json"
    request_path.write_text(json.dumps(request, ensure_ascii=False))
    if not response_path.exists():
        run_hermes(request_path, response_path, directory / f"hermes-{attempt}.log")
    response = json.loads(response_path.read_text())["response"].strip()
    if response.startswith("```json") and response.endswith("```"):
        response = response[7:-3].strip()
    return response
