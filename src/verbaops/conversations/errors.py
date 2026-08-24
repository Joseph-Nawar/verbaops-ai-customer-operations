"""Typed domain errors for trusted conversation lifecycle operations."""


class ConversationError(RuntimeError):
    """Base class for safe conversation persistence errors."""


class ConversationNotFoundError(ConversationError):
    """Raised when a conversation is absent from the trusted scope."""

    def __init__(self) -> None:
        super().__init__("conversation not found")


class ConversationBusyError(ConversationError):
    """Raised when a non-stale run already owns a conversation turn."""

    def __init__(self) -> None:
        super().__init__("conversation is busy")


class ConversationLifecycleError(ConversationError):
    """Raised when a run cannot accept the requested lifecycle operation."""


class ConversationInputError(ConversationError):
    """Raised when a caller supplies an invalid lifecycle input."""
