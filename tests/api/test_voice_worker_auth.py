"""Dedicated Voice Worker service authentication contracts."""

from dataclasses import fields
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI

from verbaops.api.dependencies import get_trusted_context, get_voice_worker_context
from verbaops.auth.context import TrustedContext
from verbaops.auth.provider import AuthenticationError, OpaqueCredential
from verbaops.voice.auth import VoiceWorkerContext, authenticate_worker

from .conftest import build_provider, build_settings, request


def add_worker_route(app: FastAPI) -> None:
    @app.get("/internal/test-worker")
    async def worker_route(
        context: Annotated[VoiceWorkerContext, Depends(get_voice_worker_context)],
    ) -> dict[str, str]:
        return {"service_name": context.service_name}


def add_customer_route(app: FastAPI) -> None:
    @app.get("/internal/test-customer")
    async def customer_route(
        _context: Annotated[TrustedContext, Depends(get_trusted_context)],
    ) -> dict[str, str]:
        return {"status": "customer"}


def _app() -> FastAPI:
    from verbaops.api.app import create_app

    return create_app(settings=build_settings(), auth_provider=build_provider())


def test_worker_context_is_fixed_service_identity_without_caller_authority() -> None:
    context = VoiceWorkerContext(service_name="voice_worker")

    assert context.service_name == "voice_worker"
    assert {field.name for field in fields(context)} == {"service_name"}
    assert not hasattr(context, "roles")
    assert not hasattr(context, "tenant_id")
    assert not hasattr(context, "customer_id")
    assert not hasattr(context, "principal_id")


def test_authenticate_worker_uses_constant_time_secret_comparison() -> None:
    context = authenticate_worker(
        OpaqueCredential("worker-secret"),
        expected_token="worker-secret",
    )
    assert context == VoiceWorkerContext(service_name="voice_worker")

    with pytest.raises(AuthenticationError):
        authenticate_worker(
            OpaqueCredential("customer-secret"),
            expected_token="worker-secret",
        )


@pytest.mark.asyncio
async def test_worker_credential_succeeds_only_on_worker_dependency() -> None:
    app = _app()
    add_worker_route(app)

    response = await request(
        app,
        "GET",
        "/internal/test-worker",
        headers={"Authorization": "Bearer local-voice-worker-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"service_name": "voice_worker"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer opaque-test-credential"},
        {"Authorization": "Bearer wrong-worker-token"},
        {"Authorization": "Basic local-voice-worker-token"},
    ],
)
async def test_customer_or_malformed_credentials_cannot_authenticate_worker(
    headers: dict[str, str],
) -> None:
    app = _app()
    add_worker_route(app)

    response = await request(app, "GET", "/internal/test-worker", headers=headers)

    assert response.status_code == 401
    assert "local-voice-worker-token" not in response.text
    assert "opaque-test-credential" not in response.text


@pytest.mark.asyncio
async def test_worker_credential_cannot_authenticate_normal_customer_dependency() -> None:
    app = _app()
    add_customer_route(app)

    response = await request(
        app,
        "GET",
        "/internal/test-customer",
        headers={"Authorization": "Bearer local-voice-worker-token"},
    )

    assert response.status_code == 401
    assert "local-voice-worker-token" not in response.text
