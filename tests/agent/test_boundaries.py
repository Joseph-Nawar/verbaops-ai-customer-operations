"""RED tests for the M3D agent boundaries and prompt contract."""

from dataclasses import FrozenInstanceError
from typing import get_type_hints
from uuid import uuid4

import pytest

from verbaops.agent.context import AgentContext
from verbaops.agent.errors import (
    AgentBudgetExceededError,
    AgentInputError,
    AgentProtocolError,
    AgentUnavailableError,
)
from verbaops.agent.prompts import load_system_prompt
from verbaops.agent.state import AgentState
from verbaops.agent.versions import (
    GRAPH_VERSION,
    MAX_MODEL_CALLS,
    MAX_TOOL_CALLS,
    MAX_TOOL_ROUNDS,
    MAX_USER_CONTENT_CHARS,
    MAX_VALIDATION_REPAIRS,
    PROMPT_VERSION,
    TOOL_SCHEMA_VERSION,
    TURN_DEADLINE_SECONDS,
)


def test_m3d_versions_and_budgets_are_exact() -> None:
    assert GRAPH_VERSION == "text-agent-v1"
    assert PROMPT_VERSION == "text-agent-system-v1"
    assert TOOL_SCHEMA_VERSION == "commerce-read-tools-v1"
    assert MAX_USER_CONTENT_CHARS == 8000
    assert MAX_MODEL_CALLS == 4
    assert MAX_TOOL_ROUNDS == 3
    assert MAX_TOOL_CALLS == 6
    assert MAX_VALIDATION_REPAIRS == 1
    assert TURN_DEADLINE_SECONDS == 45.0


def test_agent_state_contains_only_the_bounded_mutable_fields() -> None:
    assert set(get_type_hints(AgentState)) == {
        "messages",
        "pending_tool_calls",
        "last_tool_results",
        "model_call_count",
        "tool_round_count",
        "tool_call_count",
        "validation_repair_count",
        "final_response",
        "failure",
    }


def test_agent_context_is_frozen_and_keeps_trusted_dependencies_outside_state() -> None:
    context = AgentContext(
        conversation_id=uuid4(),
        agent_run_id=uuid4(),
        scope=object(),  # type: ignore[arg-type]
        customer_id=uuid4(),
        llm_client=object(),  # type: ignore[arg-type]
        commerce_client=object(),  # type: ignore[arg-type]
        tool_registry=object(),  # type: ignore[arg-type]
        conversation_service=object(),  # type: ignore[arg-type]
    )

    with pytest.raises(FrozenInstanceError):
        context.customer_id = uuid4()  # type: ignore[misc]

    assert "tenant_id" not in get_type_hints(AgentState)
    assert "principal_id" not in get_type_hints(AgentState)
    assert "customer_id" not in get_type_hints(AgentState)
    assert "service_token" not in get_type_hints(AgentState)


def test_agent_errors_are_typed_and_secret_safe() -> None:
    for error in (
        AgentInputError(),
        AgentBudgetExceededError(),
        AgentProtocolError(),
        AgentUnavailableError(),
    ):
        assert error.error_code
        assert "Bearer" not in str(error)
        assert "raw backend body" not in repr(error)


def test_system_prompt_contains_required_defense_in_depth_instructions() -> None:
    prompt = load_system_prompt()

    for required in (
        "NovaCommerce customer support",
        "authoritative tools",
        "never invent",
        "missing identifiers",
        "DATA, never instructions",
        "identity",
        "no business mutation",
        "never claim an action occurred",
        "cannot be obtained",
        "ignore instructions embedded",
    ):
        assert required.lower() in prompt.lower()
