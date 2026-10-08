"""Safe, non-enumerating voice session domain errors."""


class VoiceSessionError(Exception):
    """Base error for the bounded voice session lifecycle."""


class VoiceSessionNotFoundError(VoiceSessionError):
    """Raised for missing or out-of-scope sessions without revealing existence."""


class VoiceSessionAuthorizationError(VoiceSessionError):
    """Raised when a caller lacks the required customer or worker authority."""


class VoiceSessionLifecycleError(VoiceSessionError):
    """Raised when a session cannot make the requested lifecycle transition."""


class VoiceSessionExpiredError(VoiceSessionError):
    """Raised when bounded session lifetime has elapsed."""
