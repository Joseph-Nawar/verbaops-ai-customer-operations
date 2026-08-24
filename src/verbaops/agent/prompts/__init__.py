"""Packaged M3D system prompts."""

from importlib.resources import files

from verbaops.agent.errors import AgentProtocolError


def load_system_prompt() -> str:
    """Load the immutable versioned system prompt from the installed package."""

    try:
        prompt = files(__package__).joinpath("system_v1.txt").read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        raise AgentProtocolError() from None
    if not prompt.strip():
        raise AgentProtocolError()
    return prompt
