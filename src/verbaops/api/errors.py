"""VerbaOps AI-owned HTTP error responses."""

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from verbaops.api.dependencies import RuntimeResourceUnavailableError
from verbaops.auth.provider import AuthenticationError
from verbaops.observability.context import get_request_context


def _request_id() -> str | None:
    request_id = get_request_context().request_id
    return str(request_id) if request_id is not None else None


def _error_payload(code: str, message: str, **fields: Any) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "request_id": _request_id(), **fields}}


def internal_error_response() -> JSONResponse:
    """Build the generic response used when an exception escapes the app stack."""

    return JSONResponse(
        status_code=500,
        content=_error_payload("internal_error", "internal server error"),
    )


async def authentication_error_handler(
    _request: Request,
    _error: AuthenticationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content=_error_payload("authentication_failed", "authentication failed"),
        headers={"WWW-Authenticate": "Bearer"},
    )


async def validation_error_handler(
    _request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    details = [
        {"location": list(item.get("loc", ())), "type": item.get("type", "invalid")}
        for item in error.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            "request_validation_error",
            "request validation failed",
            details=details,
        ),
    )


async def http_exception_handler(request: Request, error: Any) -> JSONResponse:
    detail = getattr(error, "detail", "request failed")
    status_code = int(getattr(error, "status_code", 400))
    return JSONResponse(
        status_code=status_code,
        content=_error_payload("http_error", str(detail)),
        headers=dict(getattr(error, "headers", None) or {}),
    )


async def runtime_resource_error_handler(
    _request: Request,
    _error: RuntimeResourceUnavailableError,
) -> JSONResponse:
    """Return a safe application-owned response for unavailable resources."""

    return JSONResponse(
        status_code=503,
        content=_error_payload("resource_unavailable", "required runtime resource unavailable"),
    )
