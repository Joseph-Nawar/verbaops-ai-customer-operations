"""Provider-free contracts for the Stage 7 voice foundation models."""

from dataclasses import fields
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from verbaops.agent.context import InteractionMode
from verbaops.conversations.persistence import AgentRun
from verbaops.voice.domain import VoiceSessionRecord, VoiceSessionState
from verbaops.voice.models import VoiceSessionBootstrap, VoiceSessionCreateRequest


def _record(*, status: VoiceSessionState = VoiceSessionState.CREATED) -> VoiceSessionRecord:
    now = datetime.now(UTC)
    return VoiceSessionRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        principal_id=uuid4(),
        customer_id=uuid4(),
        conversation_id=uuid4(),
        transport_provider="livekit",
        stt_provider="elevenlabs_scribe_v2_realtime",
        tts_provider="elevenlabs_flash_v2_5",
        room_identity="room-opaque",
        participant_identity="participant-opaque",
        status=status,
        created_at=now,
        connected_at=None,
        ended_at=None,
        error_code=None,
    )


def test_voice_session_state_is_closed_and_record_has_only_approved_fields() -> None:
    assert [state.value for state in VoiceSessionState] == [
        "created",
        "connecting",
        "connected",
        "ended",
    ]
    assert {field.name for field in fields(VoiceSessionRecord)} == {
        "id",
        "tenant_id",
        "principal_id",
        "customer_id",
        "conversation_id",
        "transport_provider",
        "stt_provider",
        "tts_provider",
        "room_identity",
        "participant_identity",
        "status",
        "created_at",
        "connected_at",
        "ended_at",
        "error_code",
    }
    assert not {
        "roles",
        "claims",
        "token",
        "room_token",
        "raw_audio",
        "provider_payload",
    } & {field.name for field in fields(VoiceSessionRecord)}
    assert _record().status is VoiceSessionState.CREATED


def test_bootstrap_request_accepts_only_optional_conversation_id() -> None:
    request = VoiceSessionCreateRequest()
    assert request.conversation_id is None
    assert VoiceSessionCreateRequest(conversation_id=uuid4()).conversation_id is not None

    with pytest.raises(ValidationError):
        VoiceSessionCreateRequest.model_validate({"tenant_id": str(uuid4())})


def test_bootstrap_response_has_exact_bounded_browser_contract() -> None:
    VoiceSessionBootstrap(
        voice_session_id=uuid4(),
        conversation_id=uuid4(),
        livekit_url="https://voice.example.test",
        room_token="test-only-token",
        token_expires_at=datetime.now(UTC),
        status=VoiceSessionState.CREATED,
    )
    assert set(VoiceSessionBootstrap.model_fields) == {
        "voice_session_id",
        "conversation_id",
        "livekit_url",
        "room_token",
        "token_expires_at",
        "status",
    }
    assert "room_identity" not in VoiceSessionBootstrap.model_fields
    assert "participant_identity" not in VoiceSessionBootstrap.model_fields


def test_agent_run_model_freezes_text_and_voice_provenance_rules() -> None:
    assert AgentRun.__table__.c.interaction_mode.default.arg == InteractionMode.TEXT.value
    checks = {constraint.name for constraint in AgentRun.__table__.constraints}
    assert "agent_run_provenance_consistent" in checks
    assert "uq_agent_runs_one_running_per_conversation" in {
        index.name for index in AgentRun.__table__.indexes
    }
    voice_indexes = {
        index.name: str(index.dialect_options["postgresql"].get("where"))
        for index in AgentRun.__table__.indexes
        if index.name == "uq_agent_runs_voice_session_turn"
    }
    assert voice_indexes == {
        "uq_agent_runs_voice_session_turn": "voice_session_id IS NOT NULL AND voice_turn_id IS NOT NULL"
    }
