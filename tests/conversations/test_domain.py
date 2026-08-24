"""Pure M3B record and error contract tests."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from verbaops.conversations.domain import model_call_fields
from verbaops.conversations.errors import (
    ConversationBusyError,
    ConversationLifecycleError,
    ConversationNotFoundError,
)
from verbaops.conversations.persistence import (
    AgentRun,
    Conversation,
    Message,
    ModelCall,
    ToolInvocation,
)
from verbaops.conversations.repository import (
    _agent_run_record,
    _conversation_record,
    _message_record,
    _model_call_record,
    _require_running,
    _tool_invocation_record,
    utc_now,
)
from verbaops.conversations.service import ConversationService
from verbaops.llm.models import CapabilityAlias, ResponseMetadata


def test_model_call_fields_preserve_m3a_metadata_without_inference() -> None:
    fields = model_call_fields(
        ResponseMetadata(
            capability_alias=CapabilityAlias.AGENT_FAST,
            gateway_model_id="deployment-id",
            model="provider/model",
        )
    )
    assert fields == {
        "capability_alias": "agent-fast",
        "gateway_request_id": None,
        "gateway_model_id": "deployment-id",
        "model": "provider/model",
        "provider": None,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "latency_ms": None,
        "cost_usd": None,
        "finish_reason": None,
    }


def test_model_call_fields_require_the_non_nullable_capability_alias() -> None:
    with pytest.raises(ValueError, match="capability_alias is required"):
        model_call_fields(ResponseMetadata())


def test_scope_errors_are_typed_and_secret_free() -> None:
    assert str(ConversationNotFoundError()) == "conversation not found"
    assert str(ConversationBusyError()) == "conversation is busy"
    assert "secret" not in repr(ConversationNotFoundError()).lower()


def test_persistence_helpers_keep_utc_and_reject_finished_runs() -> None:
    assert utc_now().tzinfo is not None
    run = AgentRun(
        conversation_id=uuid4(),
        user_message_id=uuid4(),
        status="completed",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
        started_at=utc_now(),
    )
    with pytest.raises(ConversationLifecycleError, match="not running"):
        _require_running(run)
    service = ConversationService(None)  # type: ignore[arg-type]
    assert service._stale_after.total_seconds() == 900


def test_persistence_models_convert_to_domain_records() -> None:
    now = datetime.now(UTC)
    conversation_id = uuid4()
    message_id = uuid4()
    run_id = uuid4()
    model_call_id = uuid4()
    tool_invocation_id = uuid4()
    conversation = Conversation(
        id=conversation_id,
        tenant_id=uuid4(),
        principal_id=uuid4(),
        created_at=now,
        updated_at=now,
    )
    message = Message(
        id=message_id,
        conversation_id=conversation_id,
        sequence=1,
        role="user",
        content="hello",
        created_at=now,
    )
    run = AgentRun(
        id=run_id,
        conversation_id=conversation_id,
        user_message_id=message_id,
        assistant_message_id=None,
        status="running",
        graph_version="g",
        prompt_version="p",
        tool_schema_version="t",
        started_at=now,
        completed_at=None,
        error_code=None,
    )
    model_call = ModelCall(
        id=model_call_id,
        agent_run_id=run_id,
        sequence=1,
        capability_alias="agent-fast",
        gateway_request_id="request",
        gateway_model_id="deployment",
        model="model",
        provider="provider",
        input_tokens=1,
        output_tokens=2,
        total_tokens=3,
        latency_ms=4.0,
        cost_usd=0.0,
        finish_reason="stop",
        status="succeeded",
        error_code=None,
        created_at=now,
    )
    tool_invocation = ToolInvocation(
        id=tool_invocation_id,
        agent_run_id=run_id,
        sequence=1,
        tool_call_id="call",
        tool_name="lookup",
        risk_level="read",
        arguments_json={"id": "1"},
        result_json={"ok": True},
        status="succeeded",
        latency_ms=5.0,
        error_code=None,
        created_at=now,
        completed_at=now,
    )
    assert _conversation_record(conversation).id == conversation_id
    assert _message_record(message).id == message_id
    assert _agent_run_record(run).id == run_id
    assert _model_call_record(model_call).gateway_model_id == "deployment"
    assert _tool_invocation_record(tool_invocation).result_json == {"ok": True}
