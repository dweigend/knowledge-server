"""Run with the installed Hermes Python, keeping its provider authentication in Hermes."""

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from run_agent import AIAgent


def configured_model(configuration: dict | None = None) -> tuple[str, str]:
    """Resolve per-request choices without changing the user's Hermes configuration."""
    configuration = configuration or {}
    return (
        configuration.get("model") or "gpt-5.6-luna",
        configuration.get("provider") or "openai-codex",
    )


def create_agent(model: str, provider: str, timeout_seconds: float = 240) -> "AIAgent":
    """Reuse Hermes authentication with tools, memory and background review disabled."""
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from run_agent import AIAgent

    runtime = resolve_runtime_provider(requested=provider, target_model=model)
    return AIAgent(
        model=model,
        provider=runtime["provider"],
        api_mode=runtime["api_mode"],
        api_key=runtime["api_key"],
        base_url=runtime["base_url"],
        enabled_toolsets=[],
        skip_context_files=True,
        skip_memory=True,
        skip_background_review=True,
        quiet_mode=True,
        max_iterations=2,
        run_budget_seconds=min(180, timeout_seconds),
        reasoning_config={"effort": "medium"},
    )


def main() -> None:
    """Read one request, persist its response and always close the Hermes agent."""
    request = json.loads(Path(sys.argv[1]).read_text())
    configuration = json.loads(request.get("configuration", "{}"))
    model, provider = configured_model(configuration)
    agent = create_agent(model, provider, configuration.get("timeout_seconds", 240))
    try:
        response = run_request(agent, request, model, provider)
        Path(sys.argv[2]).write_text(json.dumps(response, ensure_ascii=False))
    finally:
        agent.close()


def run_request(agent: "AIAgent", request: dict[str, str], model: str, provider: str) -> dict:
    """Run the supplied prompt and retain the provider and session provenance."""
    result = agent.run_conversation(
        user_message=request["input"],
        system_message=request["instructions"],
    )
    return {
        "execution": "live",
        "model": getattr(agent, "model", None),
        "provider": getattr(agent, "provider", None),
        "requested_model": model,
        "requested_provider": provider,
        "response": result["final_response"],
        "session_id": agent.session_id,
    }


if __name__ == "__main__":
    main()
