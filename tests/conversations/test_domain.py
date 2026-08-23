"""Pure M3B record and error contract tests."""

from uuid import uuid4

import pytest

from verbaops.conversations.domain import model_call_fields
from verbaops.conversations.errors import (
    ConversationBusyError,
    ConversationLifecycleError,
    ConversationNotFoundError,
)
from verbaops.conversations.persistence import AgentRun
from verbaops.conversations.repository import _require_running, utc_now
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
