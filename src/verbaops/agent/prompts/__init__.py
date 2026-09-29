"""Packaged versioned system prompts."""

from importlib.resources import files

from verbaops.agent.errors import AgentProtocolError


def load_system_prompt(version: str = "v2") -> str:
    """Load one versioned system prompt from the installed package."""

    try:
        if version not in {"v2", "v3"}:
            raise AgentProtocolError()
        prompt = files(__package__).joinpath(f"system_{version}.txt").read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        raise AgentProtocolError() from None
    if not prompt.strip():
        raise AgentProtocolError()
    return prompt
