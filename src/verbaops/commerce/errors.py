"""Secret-safe typed failures from the NovaCommerce HTTP boundary."""

import re


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


_SAFE_WRITE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class CommerceWriteError(CommerceError):
    """Base for bounded write outcomes; never retains an upstream body or headers."""

    def __init__(
        self,
        *,
        status_code: int | None,
        error_code: str | None,
        _detail: object | None = None,
    ) -> None:
        del _detail
        self.status_code = status_code if status_code is None or 100 <= status_code <= 599 else None
        self.error_code = (
            error_code
            if error_code is not None and _SAFE_WRITE_ERROR_CODE.fullmatch(error_code)
            else None
        )
        super().__init__()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status_code={self.status_code!r}, "
            f"error_code={self.error_code!r})"
        )


class CommerceWriteRejected(CommerceWriteError):
    """NovaCommerce returned a definite no-mutation rejection."""

    message = "commerce write was rejected"


class CommerceWritePreDispatchError(CommerceWriteError):
    """Transport positively proved the request was not dispatched."""

    message = "commerce write was not dispatched"

    def __init__(self) -> None:
        super().__init__(status_code=None, error_code=None)


class CommerceWriteAmbiguousError(CommerceWriteError):
    """The write may have been dispatched; its outcome must be reconciled."""

    message = "commerce write outcome is ambiguous"
