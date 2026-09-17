"""Execute one generation request in the installed Hermes environment.

The bridge keeps provider authentication and model construction inside Hermes
and returns only the requested structured response.
"""

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

if __package__:
    from .generation_models import GenerationResponse, ModelConfiguration
else:
    from generation_models import GenerationResponse, ModelConfiguration


class BridgeRequest(BaseModel):
    """Decode one prompt and its separately serialized configuration."""

    input: str
    instructions: str
    configuration: str = "{}"


class RuntimeProvider(BaseModel):
    """Validate the credentials and transport selected by Hermes."""

    provider: str
    api_mode: str
    api_key: str | None
    base_url: str | None


class ConversationResult(BaseModel):
    """Read the final response from a completed Hermes conversation."""

    final_response: str


class ConversationAgent(Protocol):
    """Describe the conversation capability consumed by the bridge."""

    session_id: str

    def run_conversation(self, *, user_message: str, system_message: str) -> object:
        """Return the provider result for one supplied conversation."""
        ...

    def close(self) -> None:
        """Release the provider resources after the request."""
        ...


def create_agent(
    model: str,
    provider: str,
    timeout_seconds: float = 240,
    reasoning_effort: str = "max",
) -> ConversationAgent:
    """Reuse Hermes authentication with tools, memory and background review disabled."""
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from run_agent import AIAgent

    runtime = RuntimeProvider.model_validate(
        resolve_runtime_provider(requested=provider, target_model=model)
    )
    return AIAgent(
        model=model,
        provider=runtime.provider,
        api_mode=runtime.api_mode,
        api_key=runtime.api_key,
        base_url=runtime.base_url,
        enabled_toolsets=[],
        skip_context_files=True,
        skip_memory=True,
        skip_background_review=True,
        quiet_mode=True,
        max_iterations=2,
        run_budget_seconds=min(180, timeout_seconds),
        reasoning_config={"effort": reasoning_effort},
    )


def main() -> None:
    """Read one request, persist its response and always close the Hermes agent."""
    request = BridgeRequest.model_validate_json(Path(sys.argv[1]).read_text())
    configuration = ModelConfiguration.model_validate_json(request.configuration)
    model = configuration.model or "gpt-5.6-luna"
    provider = configuration.provider or "openai-codex"
    agent = create_agent(
        model, provider, configuration.timeout_seconds, configuration.reasoning_effort
    )
    try:
        response = run_request(agent, request, model, provider)
        Path(sys.argv[2]).write_text(response.model_dump_json())
    finally:
        agent.close()


def run_request(
    agent: ConversationAgent,
    request: BridgeRequest | Mapping[str, object],
    model: str,
    provider: str,
) -> GenerationResponse:
    """Run the supplied prompt and retain the provider and session provenance."""
    request = BridgeRequest.model_validate(request)
    result = ConversationResult.model_validate(
        agent.run_conversation(user_message=request.input, system_message=request.instructions)
    )
    return GenerationResponse(
        model=getattr(agent, "model", None),
        provider=getattr(agent, "provider", None),
        requested_model=model,
        requested_provider=provider,
        response=result.final_response,
        session_id=agent.session_id,
    )


if __name__ == "__main__":
    main()
