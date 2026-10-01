"""Packaged versioned system prompts."""

from importlib.resources import files

from verbaops.agent.errors import AgentProtocolError


def load_system_prompt(version: str = "v2") -> str:
    """Load one versioned system prompt from the installed package."""

    try:
        prompt_resources = {
            "v2": "system_v2.txt",
            "v3": "system_v3.txt",
            "p4-evidence-linked-v1": "system_p4_evidence_linked_v1.txt",
        }
        if version not in prompt_resources:
            raise AgentProtocolError()
        prompt = files(__package__).joinpath(prompt_resources[version]).read_text(
            encoding="utf-8"
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        raise AgentProtocolError() from None
    if not prompt.strip():
        raise AgentProtocolError()
    return prompt
