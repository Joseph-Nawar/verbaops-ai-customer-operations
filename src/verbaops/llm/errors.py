"""Safe, typed failures raised by the VerbaOps LLM gateway boundary."""


class LLMError(Exception):
    """Base error that deliberately discards unsafe gateway diagnostics."""

    message = "LLM gateway request failed"

    def __init__(self, _detail: object | None = None) -> None:
        super().__init__(self.message)


class LLMTimeoutError(LLMError):
    """The configured gateway request timeout elapsed."""

    message = "LLM gateway request timed out"


class LLMAuthenticationError(LLMError):
    """The gateway rejected the supplied credentials."""

    message = "LLM gateway authentication failed"


class LLMRateLimitError(LLMError):
    """The gateway refused the request because of a rate limit."""

    message = "LLM gateway rate limit exceeded"


class LLMUnavailableError(LLMError):
    """The gateway or its upstream provider is unavailable."""

    message = "LLM gateway is unavailable"


class LLMProtocolError(LLMError):
    """The gateway returned a response outside the expected protocol."""

    message = "LLM gateway returned an invalid response"


class LLMStructuredOutputError(LLMError):
    """The gateway content could not satisfy the requested structured model."""

    message = "LLM structured output was invalid"
