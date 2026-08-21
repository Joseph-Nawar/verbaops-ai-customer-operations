"""Safe, machine-readable NovaCommerce API errors."""

from collections.abc import Mapping

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class APIError(Exception):
    """One small error type for all expected business/API failures."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = dict(headers or {})


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


async def api_error_handler(_: Request, error: APIError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=error_body(error.code, error.message),
        headers=error.headers,
    )


async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body("invalid_query", "Request validation failed."),
    )
