"""Safe typed failures for the bounded read-only agent runtime."""

from typing import ClassVar


class AgentError(RuntimeError):
    """Base class for safe agent-runtime failures."""

    error_code: ClassVar[str] = "agent_error"
    message: ClassVar[str] = "agent runtime failed"

    def __init__(self) -> None:
        super().__init__(self.message)


class AgentInputError(AgentError):
    """Raised when user content violates the bounded turn input contract."""

    error_code = "agent_input_invalid"
    message = "agent input is invalid"


class AgentBusyError(AgentError):
    """Raised when another non-stale run owns the conversation turn."""

    error_code = "agent_busy"
    message = "conversation is busy"


class AgentUnavailableError(AgentError):
    """Raised when a required LLM or Commerce dependency is unavailable."""

    error_code = "agent_unavailable"
    message = "agent dependencies are unavailable"


class AgentBudgetExceededError(AgentError):
    """Raised when a server-side turn budget is exceeded."""

    error_code = "agent_budget_exceeded"
    message = "agent turn budget exceeded"


class AgentProtocolError(AgentError):
    """Raised when model output cannot be safely used by the graph."""

    error_code = "agent_protocol_error"
    message = "agent response was invalid"
