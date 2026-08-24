"""Secret-safe typed failures from the NovaCommerce HTTP boundary."""


class CommerceError(RuntimeError):
    """Base class for safe, application-owned Commerce failures."""

    message = "commerce request failed"

    def __init__(self, _detail: object | None = None) -> None:
        del _detail
        super().__init__(self.message)


class CommerceAuthenticationError(CommerceError):
    """The Commerce API rejected service authentication."""

    message = "commerce authentication failed"


class CommerceNotFoundError(CommerceError):
    """The requested Commerce resource was not found."""

    message = "commerce resource not found"


class CommerceTimeoutError(CommerceError):
    """The Commerce API did not respond before the configured timeout."""

    message = "commerce request timed out"


class CommerceUnavailableError(CommerceError):
    """The Commerce API or transport is temporarily unavailable."""

    message = "commerce service unavailable"


class CommerceProtocolError(CommerceError):
    """The Commerce API returned an unexpected protocol or schema response."""

    message = "invalid commerce response"
