"""Generate cached, schema-validated proposals through a Hermes subprocess.

Requests support cancellation and limited repair while raw model output remains
untrusted until structural and domain validation succeed.
"""

import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from typing import Literal, Self

from pydantic import Field, ValidationError, model_validator

from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.runtime_support import workflow_event_log as events

HERMES_PYTHON = Path(
    os.environ.get(
        "KNOWLEDGE_HERMES_PYTHON", str(Path.home() / ".hermes/hermes-agent/venv/bin/python")
    )
)

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"]


class ModelConfiguration(models.Contract):
    """Pin the bounded, tool-free Hermes request configuration."""

    model: str | None = Field(default=None, min_length=1)
    provider: str | None = Field(default=None, min_length=1)
    reasoning_effort: ReasoningEffort = "max"
    max_attempts: int = Field(default=2, ge=1, le=2)
    timeout_seconds: float = Field(default=240, ge=1, le=240)
    allowed_tools: list[str] = Field(default_factory=list)
    cost_limit_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def reject_unsupported_capabilities(self) -> Self:
        """Reject limits or capabilities that the adapter cannot enforce."""
        if self.allowed_tools:
            raise ValueError("This Hermes adapter does not support tool execution")
        if self.cost_limit_usd is not None:
            raise ValueError("This Hermes adapter cannot enforce a monetary cost limit")
        return self

    def resolved(self) -> "ModelConfiguration":
        """Make the existing Luna defaults explicit before hashing a request."""
        return self.model_copy(
            update={
                "model": self.model or "gpt-5.6-luna",
                "provider": self.provider or "openai-codex",
            }
        )


def check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    """Stop before further work when the caller cancels this request."""
    if cancelled is not None and cancelled():
        raise InterruptedError("Model request cancelled")


def generate[T: models.Contract](
    instructions: str,
    packet: str,
    contract: type[T],
    output_directory: Path,
    validate: Callable[[T], None] | None = None,
    *,
    configuration: ModelConfiguration | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> T:
    """Reuse a validated proposal or request at most two schema-checked attempts."""
    check_cancelled(cancelled)
    configuration = (configuration or ModelConfiguration()).resolved()
    schema = json.dumps(contract.model_json_schema(), ensure_ascii=False)
    request = {"instructions": instructions, "input": f"SCHEMA:\n{schema}\n\nINPUT:\n{packet}"}
    request["configuration"] = configuration.model_dump_json()
    identity = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    directory = output_directory / identity
    directory.mkdir(parents=True, exist_ok=True)
    accepted = directory / "validated.json"
    cached = load_cached_proposal(accepted, contract, validate)
    if cached is not None:
        events.record_event(directory, "model_cache_reused", contract=contract.__name__)
        return cached
    return generate_attempts(request, directory, contract, validate, configuration, cancelled)


def generate_attempts[T: models.Contract](
    request: dict[str, str],
    directory: Path,
    contract: type[T],
    validate: Callable[[T], None] | None,
    configuration: ModelConfiguration,
    cancelled: Callable[[], bool] | None,
) -> T:
    """Try the initial request and one repair, preserving every response for inspection."""
    accepted = directory / "validated.json"
    for attempt in range(configuration.max_attempts):
        check_cancelled(cancelled)
        started = monotonic()
        try:
            response = request_response(request, directory, attempt, cancelled=cancelled)
            check_cancelled(cancelled)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
            events.record_event(
                directory,
                "model_attempt_failed",
                attempt=attempt + 1,
                status="cancelled" if isinstance(error, InterruptedError) else "failed",
                error_type=type(error).__name__,
                elapsed_seconds=round(monotonic() - started, 2),
            )
            raise
        errors: list[str] = []
        proposal = validate_response(response, request, contract, validate, errors=errors)
        events.record_event(
            directory,
            "model_attempt",
            attempt=attempt + 1,
            status="rejected" if proposal is None else "validated",
            elapsed_seconds=round(monotonic() - started, 2),
            contract=contract.__name__,
            validation_errors=errors,
        )
        if proposal is None:
            continue
        accepted.write_text(proposal.model_dump_json(indent=2))
        return proposal
    raise ValueError(f"Model output failed contract validation; inspect {directory}")


def validate_response[T: models.Contract](
    response: str,
    request: dict[str, str],
    contract: type[T],
    validate: Callable[[T], None] | None,
    *,
    errors: list[str] | None = None,
) -> T | None:
    """Validate a response or add its errors to the request for the repair attempt."""
    try:
        proposal = contract.model_validate_json(response)
        validate_proposal(proposal, validate)
        return proposal
    except ValueError as error:
        if errors is not None:
            errors.append(str(error))
        if isinstance(error, ValidationError) and error.errors()[0]["type"] == "json_invalid":
            request["input"] = "SCHEMA:\n" + json.dumps(contract.model_json_schema())
        request["input"] += (
            f"\nPrevious invalid output:\n{response}\nValidation errors:\n{error}\n"
            "Return complete, indented, syntactically valid JSON. No dangling quotes or commas. "
            "Preserve valid content. Use verbatim quotes from the supplied pages; "
            "omit invalid relations."
        )
        return None


def validate_proposal[T: models.Contract](
    proposal: T, validate: Callable[[T], None] | None
) -> None:
    """Apply optional domain checks after structural contract validation."""
    if validate is None:
        return
    validate(proposal)


def load_cached_proposal[T: models.Contract](
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


def run_hermes(
    request_path: Path,
    response_path: Path,
    log_path: Path,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    """Run the installed Hermes adapter with a timeout and a private diagnostic log."""
    request = json.loads(request_path.read_text())
    configuration = ModelConfiguration.model_validate_json(request["configuration"])
    arguments = [
        str(HERMES_PYTHON),
        str(Path(__file__).with_name("hermes_bridge.py")),
        str(request_path),
        str(response_path),
    ]
    check_cancelled(cancelled)
    with log_path.open("w") as log:
        if cancelled is None:
            subprocess.run(
                arguments, stdout=log, stderr=log, check=True, timeout=configuration.timeout_seconds
            )
            return
        with subprocess.Popen(arguments, stdout=log, stderr=log) as process:
            wait_for_hermes(process, configuration.timeout_seconds, cancelled)


def wait_for_hermes(
    process: subprocess.Popen,
    timeout_seconds: float,
    cancelled: Callable[[], bool],
) -> None:
    """Poll cancellation and terminate the external request on cancellation or timeout."""
    deadline = monotonic() + timeout_seconds
    try:
        while True:
            check_cancelled(cancelled)
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("Hermes request exceeded its time limit")
            try:
                return_code = process.wait(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired:
                continue
            if return_code:
                raise subprocess.CalledProcessError(return_code, process.args)
            return
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def request_response(
    request: dict[str, str],
    directory: Path,
    attempt: int,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> str:
    """Reuse recorded responses and preserve changed repair requests separately."""
    request_path = directory / f"request-{attempt}.json"
    response_path = directory / f"response-{attempt}.json"
    if request_path.exists() and json.loads(request_path.read_text()) != request:
        suffix = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16]
        request_path = directory / f"request-{attempt}-{suffix}.json"
        response_path = directory / f"response-{attempt}-{suffix}.json"
    request_path.write_text(json.dumps(request, ensure_ascii=False))
    cached = response_path.exists()
    events.record_event(
        directory,
        "model_request",
        attempt=attempt + 1,
        request_file=request_path.name,
        response_file=response_path.name,
        execution="cached" if cached else "live",
    )
    if not cached:
        log_path = directory / f"hermes-{attempt}.log"
        if cancelled is None:
            run_hermes(request_path, response_path, log_path)
        else:
            run_hermes(request_path, response_path, log_path, cancelled=cancelled)
    recorded = json.loads(response_path.read_text())
    events.record_event(
        directory,
        "model_response",
        attempt=attempt + 1,
        response_file=response_path.name,
        execution="cached" if cached else "live",
        response_origin=recorded.get("execution", "unverified"),
        model=recorded.get("model"),
        provider=recorded.get("provider"),
    )
    response = recorded["response"].strip()
    if response.startswith("```json") and response.endswith("```"):
        response = response[7:-3].strip()
    return response
