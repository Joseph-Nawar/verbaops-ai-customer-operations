"""Customer-only Stage 7 voice-session HTTP contracts."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI

from verbaops.api.dependencies import get_voice_session_service
from verbaops.api.errors import PublicAPIError
from verbaops.auth.context import Role, TrustedContext
from verbaops.voice.domain import VoiceSessionRecord, VoiceSessionState
from verbaops.voice.models import VoiceSessionBootstrap

from .conftest import build_provider, build_settings, request

SESSION_ID = UUID("40000000-0000-4000-8000-000000000001")
CONVERSATION_ID = UUID("40000000-0000-4000-8000-000000000002")


def _context(
    roles: frozenset[Role], *, principal_id: str = "30000000-0000-0000-0000-000000000001"
) -> TrustedContext:
    return TrustedContext(
        principal_id=UUID(principal_id),
        tenant_id=UUID("30000000-0000-0000-0000-000000000002"),
        customer_id=UUID("30000000-0000-0000-0000-000000000003"),
        roles=roles,
    )


def _record(
    context: TrustedContext, status: VoiceSessionState = VoiceSessionState.CREATED
) -> VoiceSessionRecord:
    now = datetime.now(UTC)
    assert context.customer_id is not None
    return VoiceSessionRecord(
        id=SESSION_ID,
        tenant_id=context.tenant_id,
        principal_id=context.principal_id,
        customer_id=context.customer_id,
        conversation_id=CONVERSATION_ID,
        transport_provider="livekit",
        stt_provider="stt",
        tts_provider="tts",
        room_identity="voice-room-opaque",
        participant_identity="voice-participant-opaque",
        status=status,
        created_at=now,
        connected_at=None,
        ended_at=now if status is VoiceSessionState.ENDED else None,
        error_code=None,
    )


class FakeVoiceSessionService:
    def __init__(self, context: TrustedContext) -> None:
        self.context = context
        self.ended: list[UUID] = []

    async def create_customer_session(
        self,
        trusted_context: TrustedContext,
        conversation_id: UUID | None,
    ) -> VoiceSessionBootstrap:
        assert trusted_context == self.context
        assert conversation_id in (None, CONVERSATION_ID)
        return VoiceSessionBootstrap.model_validate(
            {
                "voice_session_id": SESSION_ID,
                "conversation_id": CONVERSATION_ID,
                "livekit_url": "wss://livekit.example.test",
                "room_token": "short-lived-test-token",
                "token_expires_at": datetime.now(UTC),
                "status": VoiceSessionState.CREATED,
            }
        )

    async def end_customer_session(
        self,
        session_id: UUID,
        trusted_context: TrustedContext,
    ) -> VoiceSessionRecord:
        assert trusted_context == self.context
        self.ended.append(session_id)
        return _record(self.context, VoiceSessionState.ENDED)


def _app(context: TrustedContext) -> tuple[FastAPI, FakeVoiceSessionService]:
    from verbaops.api.app import create_app

    service = FakeVoiceSessionService(context)
    app = create_app(settings=build_settings(), auth_provider=build_provider(context))
    app.dependency_overrides[get_voice_session_service] = lambda: service
    return app, service


@pytest.mark.asyncio
async def test_customer_bootstrap_returns_exact_server_owned_contract() -> None:
    app, _service = _app(_context(frozenset({Role.CUSTOMER})))

    response = await request(
        app,
        "POST",
        "/v1/voice/sessions",
        headers={"Authorization": "Bearer opaque-test-credential"},
        json={},
    )

    assert response.status_code == 201
    assert set(response.json()) == {
        "voice_session_id",
        "conversation_id",
        "livekit_url",
        "room_token",
        "token_expires_at",
        "status",
    }
    assert response.json()["status"] == "created"
    assert "room_name" not in response.json()
    assert "participant_identity" not in response.json()
    assert "access_token" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "roles",
    [
        frozenset({Role.CUSTOMER, Role.SUPPORT_AGENT}),
        frozenset({Role.CUSTOMER, Role.SUPPORT_SUPERVISOR}),
        frozenset({Role.CUSTOMER, Role.TENANT_ADMIN}),
    ],
)
async def test_composed_customer_roles_reach_customer_voice_service(roles: frozenset[Role]) -> None:
    app, _service = _app(_context(roles))

    response = await request(
        app,
        "POST",
        "/v1/voice/sessions",
        headers={"Authorization": "Bearer opaque-test-credential"},
        json={"conversation_id": str(CONVERSATION_ID)},
    )

    assert response.status_code == 201


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "roles",
    [
        frozenset({Role.SUPPORT_AGENT}),
        frozenset({Role.SUPPORT_SUPERVISOR}),
        frozenset({Role.TENANT_ADMIN}),
    ],
)
async def test_non_customer_context_is_rejected_by_service_boundary(roles: frozenset[Role]) -> None:
    context = _context(roles)
    app, _service = _app(context)

    async def deny(
        _trusted_context: TrustedContext,
        _conversation_id: UUID | None,
    ) -> VoiceSessionBootstrap:
        raise PublicAPIError(403, "customer_context_required", "customer context is required")

    _service.create_customer_session = deny  # type: ignore[assignment]
    response = await request(
        app,
        "POST",
        "/v1/voice/sessions",
        headers={"Authorization": "Bearer opaque-test-credential"},
        json={},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "customer_context_required"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"tenant_id": str(uuid4())},
        {"principal_id": str(uuid4())},
        {"customer_id": str(uuid4())},
        {"room_identity": "attacker-room"},
        {"participant_identity": "attacker-participant"},
        {"roles": ["tenant_admin"]},
        {"grant": "room_admin"},
        {"conversation_id": "not-a-uuid"},
    ],
)
async def test_bootstrap_rejects_forged_identity_grant_and_invalid_fields(
    body: dict[str, Any],
) -> None:
    app, _service = _app(_context(frozenset({Role.CUSTOMER})))

    response = await request(
        app,
        "POST",
        "/v1/voice/sessions",
        headers={"Authorization": "Bearer opaque-test-credential"},
        json=body,
    )

    assert response.status_code == 422
    assert "attacker" not in response.text


@pytest.mark.asyncio
async def test_end_route_accepts_no_body_and_repeated_end_is_safe() -> None:
    context = _context(frozenset({Role.CUSTOMER}))
    app, service = _app(context)

    first = await request(
        app,
        "POST",
        f"/v1/voice/sessions/{SESSION_ID}/end",
        headers={"Authorization": "Bearer opaque-test-credential"},
    )
    second = await request(
        app,
        "POST",
        f"/v1/voice/sessions/{SESSION_ID}/end",
        headers={"Authorization": "Bearer opaque-test-credential"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert service.ended == [SESSION_ID, SESSION_ID]


@pytest.mark.asyncio
async def test_end_route_rejects_arbitrary_body_fields() -> None:
    app, _service = _app(_context(frozenset({Role.CUSTOMER})))

    response = await request(
        app,
        "POST",
        f"/v1/voice/sessions/{SESSION_ID}/end",
        headers={"Authorization": "Bearer opaque-test-credential"},
        json={"roles": ["tenant_admin"], "customer_id": str(uuid4())},
    )

    assert response.status_code == 422
