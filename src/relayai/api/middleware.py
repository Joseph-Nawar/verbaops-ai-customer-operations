"""Pure-ASGI request and correlation context middleware."""

import logging
import time
from typing import Any, cast
from uuid import UUID, uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from relayai.api.errors import internal_error_response
from relayai.observability.context import bind_request_context, clear_request_context


def _incoming_header(scope: Scope, name: bytes) -> str | None:
    headers = cast(list[tuple[bytes, bytes]], scope.get("headers", []))
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _correlation_id(scope: Scope) -> UUID:
    incoming = _incoming_header(scope, b"x-correlation-id")
    if incoming is not None:
        try:
            return UUID(incoming)
        except ValueError:
            pass
    return uuid4()


class RequestContextMiddleware:
    """Establish and clear request-local identifiers without per-request state."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger("relayai.http")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4()
        correlation_id = _correlation_id(scope)
        bind_request_context(request_id, correlation_id)
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_context(message: Message) -> None:
            nonlocal response_started, status_code
            if message.get("type") == "http.response.start":
                response_started = True
                response_start = cast(dict[str, Any], message)
                status_code = int(response_start["status"])
                response_headers = list(response_start.get("headers", []))
                response_headers.extend(
                    [
                        (b"x-request-id", str(request_id).encode("ascii")),
                        (b"x-correlation-id", str(correlation_id).encode("ascii")),
                    ]
                )
                response_start["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        except Exception:
            duration_ms = max(0.0, (time.perf_counter() - started) * 1000)
            self.logger.exception(
                "request_failed",
                extra={
                    "method": scope.get("method", ""),
                    "path": scope.get("path", ""),
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 3),
                },
            )
            if response_started:
                raise
            await internal_error_response()(scope, receive, send_with_context)
        else:
            duration_ms = max(0.0, (time.perf_counter() - started) * 1000)
            self.logger.info(
                "request_completed",
                extra={
                    "method": scope.get("method", ""),
                    "path": scope.get("path", ""),
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 3),
                },
            )
        finally:
            clear_request_context()
