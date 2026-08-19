"""Structured logging tests."""

import json
import logging
from datetime import datetime
from io import StringIO
from typing import Annotated, Any, cast
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI

from relayai.api.app import create_app
from relayai.api.dependencies import get_trusted_context
from relayai.auth.context import TrustedContext
from relayai.observability.context import (
    bind_request_context,
    bind_tenant_id,
    clear_request_context,
)
from relayai.observability.logging import JsonFormatter
from tests.api.conftest import build_provider, build_settings, request


def test_json_formatter_emits_context_and_request_metadata() -> None:
    request_id = UUID("50000000-0000-0000-0000-000000000001")
    correlation_id = UUID("50000000-0000-0000-0000-000000000002")
    tenant_id = UUID("50000000-0000-0000-0000-000000000003")
    bind_request_context(request_id, correlation_id)
    bind_tenant_id(tenant_id)

    try:
        record = logging.LogRecord(
            name="relayai.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="request_completed",
            args=(),
            exc_info=None,
        )
        record.method = "GET"
        record.path = "/health"
        record.status_code = 200
        record.duration_ms = 1.25

        payload = json.loads(JsonFormatter().format(record))

        assert payload["event"] == "request_completed"
        assert payload["method"] == "GET"
        assert payload["path"] == "/health"
        assert payload["status_code"] == 200
        assert payload["duration_ms"] == 1.25
        assert payload["request_id"] == str(request_id)
        assert payload["correlation_id"] == str(correlation_id)
        assert payload["tenant_id"] == str(tenant_id)
        assert "conversation_id" not in payload
        assert datetime.fromisoformat(payload["timestamp"]).tzinfo is not None
    finally:
        clear_request_context()


def add_authenticated_log_route(app: FastAPI) -> None:
    @app.get("/test/log-context")
    async def log_context(
        _context: Annotated[TrustedContext, Depends(get_trusted_context)],
    ) -> dict[str, str]:
        return {"status": "ok"}


@pytest.mark.asyncio
async def test_actual_request_log_is_json_sanitized_and_correlated() -> None:
    app = create_app(settings=build_settings(), auth_provider=build_provider())
    add_authenticated_log_route(app)
    logger = logging.getLogger("relayai")
    handlers = [
        cast(logging.StreamHandler[Any], handler)
        for handler in logger.handlers
        if getattr(handler, "_relayai_json_handler", False)
    ]
    assert len(handlers) == 1
    stream = StringIO()
    old_stream = handlers[0].setStream(stream)

    try:
        response = await request(
            app,
            "GET",
            "/test/log-context?query-secret=must-not-be-logged",
            headers={
                "Authorization": "Bearer opaque-test-credential",
                "X-Tenant-ID": "90000000-0000-0000-0000-000000000001",
            },
        )
    finally:
        handlers[0].setStream(old_stream)

    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    completion = next(record for record in records if record["event"] == "request_completed")

    assert response.status_code == 200
    assert completion["method"] == "GET"
    assert completion["path"] == "/test/log-context"
    assert completion["status_code"] == 200
    assert completion["duration_ms"] >= 0
    assert completion["request_id"] == response.headers["X-Request-ID"]
    assert completion["correlation_id"] == response.headers["X-Correlation-ID"]
    assert completion["tenant_id"] == "30000000-0000-0000-0000-000000000002"
    serialized = stream.getvalue()
    assert "query-secret" not in serialized
    assert "opaque-test-credential" not in serialized
    assert "90000000-0000-0000-0000-000000000001" not in serialized


def test_repeated_application_creation_does_not_duplicate_handlers() -> None:
    first = create_app(settings=build_settings(), auth_provider=build_provider())
    before = [
        handler
        for handler in logging.getLogger("relayai").handlers
        if getattr(handler, "_relayai_json_handler", False)
    ]

    create_app(settings=build_settings(), auth_provider=build_provider())
    after = [
        handler
        for handler in logging.getLogger("relayai").handlers
        if getattr(handler, "_relayai_json_handler", False)
    ]

    assert first is not None
    assert len(before) == 1
    assert len(after) == 1
