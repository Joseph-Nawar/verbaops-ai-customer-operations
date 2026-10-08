"""RED-first tests for the strict internal final-transcript boundary."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI

from verbaops.agent.errors import AgentVoiceTurnFailedError, AgentVoiceTurnInProgressError
from verbaops.api.dependencies import (
    get_agent_runtime,
    get_voice_session_service,
    get_voice_worker_context,
)
from verbaops.auth.context import Role, TrustedContext
from verbaops.voice.auth import VoiceWorkerContext
from verbaops.voice.domain import VoiceSessionRecord, VoiceSessionState
from verbaops.voice.errors import VoiceSessionLifecycleError

from .conftest import build_provider, build_settings, request

SESSION_ID = UUID("50000000-0000-4000-8000-000000000001")
CONVERSATION_ID = UUID("50000000-0000-4000-8000-000000000002")
VOICE_TURN_ID = UUID("50000000-0000-4000-8000-000000000003")
TENANT_ID = UUID("50000000-0000-4000-8000-000000000004")
PRINCIPAL_ID = UUID("50000000-0000-4000-8000-000000000005")
CUSTOMER_ID = UUID("50000000-0000-4000-8000-000000000006")


def _record(status: VoiceSessionState = VoiceSessionState.CONNECTED) -> VoiceSessionRecord:
    now = datetime.now(UTC)
    return VoiceSessionRecord(
        id=SESSION_ID,
        tenant_id=TENANT_ID,
        principal_id=PRINCIPAL_ID,
        customer_id=CUSTOMER_ID,
        conversation_id=CONVERSATION_ID,
        transport_provider="livekit",
        stt_provider="stt",
        tts_provider="tts",
        room_identity="opaque-room",
        participant_identity="opaque-participant",
        status=status,
        created_at=now,
        connected_at=now if status is VoiceSessionState.CONNECTED else None,
        ended_at=now if status is VoiceSessionState.ENDED else None,
        error_code=None,
    )


class FakeVoiceSessionService:
    def __init__(self, record: VoiceSessionRecord) -> None:
        self.record = record
        self.worker_contexts: list[VoiceWorkerContext] = []

    async def get_connected_worker_session(
        self, session_id: UUID, worker_context: VoiceWorkerContext
    ) -> VoiceSessionRecord:
        assert session_id == self.record.id
        self.worker_contexts.append(worker_context)
        if self.record.status is not VoiceSessionState.CONNECTED:
            raise VoiceSessionLifecycleError()
        return self.record


class FakeAgentRuntime:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        agent_run_id = uuid4()
        assistant_message_id = uuid4()
        self.result = SimpleNamespace(
            conversation_id=CONVERSATION_ID,
            agent_run_id=agent_run_id,
            assistant_message_id=assistant_message_id,
            content="Your answer.",
            agent_run=SimpleNamespace(
                id=agent_run_id,
                voice_session_id=SESSION_ID,
                voice_turn_id=VOICE_TURN_ID,
            ),
            user_message=SimpleNamespace(id=uuid4()),
            assistant_message=SimpleNamespace(id=assistant_message_id, content="Your answer."),
            action_requests=(),
        )

    async def run_turn(
        self,
        trusted_context: TrustedContext,
        conversation_id: UUID,
        content: str,
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            {
                "trusted_context": trusted_context,
                "conversation_id": conversation_id,
                "content": content,
                **kwargs,
            }
        )
        return self.result


def _app(
    *,
    record: VoiceSessionRecord | None = None,
    runtime: FakeAgentRuntime | None = None,
    override_worker: bool = True,
) -> tuple[FastAPI, FakeVoiceSessionService, FakeAgentRuntime]:
    from verbaops.api.app import create_app

    service = FakeVoiceSessionService(record or _record())
    agent_runtime = runtime or FakeAgentRuntime()
    app = create_app(
        settings=build_settings(),
        auth_provider=build_provider(),
    )
    app.dependency_overrides[get_voice_session_service] = lambda: service
    app.dependency_overrides[get_agent_runtime] = lambda: agent_runtime
    if override_worker:
        app.dependency_overrides[get_voice_worker_context] = lambda: VoiceWorkerContext()
    return app, service, agent_runtime


@pytest.mark.asyncio
async def test_final_transcript_reconstructs_exact_customer_context() -> None:
    app, service, runtime = _app()

    response = await request(
        app,
        "POST",
        f"/internal/voice/sessions/{SESSION_ID}/final-transcripts",
        json={"voice_turn_id": str(VOICE_TURN_ID), "transcript": "Where is my order?"},
    )

    assert response.status_code == 200
    assert set(response.json()) == {
        "voice_session_id",
        "conversation_id",
        "voice_turn_id",
        "agent_run_id",
        "assistant_message_id",
        "assistant_text",
        "outcome",
        "action_requests",
        "action_prompt",
    }
    assert response.json()["voice_session_id"] == str(SESSION_ID)
    assert response.json()["conversation_id"] == str(CONVERSATION_ID)
    assert response.json()["voice_turn_id"] == str(VOICE_TURN_ID)
    assert response.json()["outcome"] == "normal_answer"
    assert response.json()["action_prompt"] is None
    assert service.worker_contexts == [VoiceWorkerContext()]
    assert len(runtime.calls) == 1
    call = runtime.calls[0]
    context = call["trusted_context"]
    assert context.tenant_id == TENANT_ID
    assert context.principal_id == PRINCIPAL_ID
    assert context.customer_id == CUSTOMER_ID
    assert context.roles == frozenset({Role.CUSTOMER})
    assert call["conversation_id"] == CONVERSATION_ID
    assert call["content"] == "Where is my order?"
    assert call["interaction_mode"] == "voice"
    assert call["voice_session_id"] == SESSION_ID
    assert call["voice_turn_id"] == VOICE_TURN_ID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"voice_turn_id": str(VOICE_TURN_ID)},
        {"transcript": "hello"},
        {"voice_turn_id": str(VOICE_TURN_ID), "transcript": "   "},
        {"voice_turn_id": str(VOICE_TURN_ID), "transcript": "x" * 4001},
        {"voice_turn_id": "not-a-uuid", "transcript": "hello"},
        {
            "voice_turn_id": str(VOICE_TURN_ID),
            "transcript": "hello",
            "roles": ["tenant_admin"],
        },
        {
            "voice_turn_id": str(VOICE_TURN_ID),
            "transcript": "hello",
            "customer_id": str(uuid4()),
        },
    ],
)
async def test_final_transcript_request_is_exactly_two_bounded_fields(body: dict[str, Any]) -> None:
    app, _service, runtime = _app()

    response = await request(
        app,
        "POST",
        f"/internal/voice/sessions/{SESSION_ID}/final-transcripts",
        json=body,
    )

    assert response.status_code == 422
    assert runtime.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [VoiceSessionState.CREATED, VoiceSessionState.CONNECTING, VoiceSessionState.ENDED],
)
async def test_final_transcript_requires_connected_session(status: VoiceSessionState) -> None:
    app, _service, runtime = _app(record=_record(status))

    response = await request(
        app,
        "POST",
        f"/internal/voice/sessions/{SESSION_ID}/final-transcripts",
        json={"voice_turn_id": str(VOICE_TURN_ID), "transcript": "hello"},
    )

    assert response.status_code == 409
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_customer_bearer_cannot_authenticate_worker_transcript_route() -> None:
    app, _service, runtime = _app(override_worker=False)

    response = await request(
        app,
        "POST",
        f"/internal/voice/sessions/{SESSION_ID}/final-transcripts",
        headers={"Authorization": "Bearer opaque-test-credential"},
        json={"voice_turn_id": str(VOICE_TURN_ID), "transcript": "hello"},
    )

    assert response.status_code == 401
    assert runtime.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (AgentVoiceTurnInProgressError(), 409, "voice_turn_in_progress"),
        (AgentVoiceTurnFailedError("agent_unavailable"), 502, "voice_turn_failed"),
    ],
)
async def test_duplicate_voice_turn_errors_are_bounded_at_http_boundary(
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    class ErrorRuntime(FakeAgentRuntime):
        async def run_turn(self, *_args: Any, **_kwargs: Any) -> Any:
            raise error

    app, _service, _runtime = _app(runtime=ErrorRuntime())

    response = await request(
        app,
        "POST",
        f"/internal/voice/sessions/{SESSION_ID}/final-transcripts",
        json={"voice_turn_id": str(VOICE_TURN_ID), "transcript": "hello"},
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
