"""Tests for immutable application-owned evaluation models."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from verbaops.evaluation.models import (
    EvaluationCase,
    EvaluationObservation,
    MetricValue,
    ObservedToolCall,
    SafetyOutcome,
)

CUSTOMER_ID = UUID("d77809e8-6d3b-5792-9128-ff2bc88bc955")


def make_case(**overrides: object) -> EvaluationCase:
    data: dict[str, object] = {
        "case_id": "order-status-001",
        "dataset_version": "text-agent-v0.1",
        "split": "dev",
        "language": "en",
        "category": "order-status",
        "customer_id": CUSTOMER_ID,
        "conversation": ({"role": "user", "content": "Where is my order?"},),
        "expected_tool": "get_order_status",
        "expected_arguments": {"order_id": "54d93c0f-951e-5d74-afdd-80d33d4c8c95"},
        "expected_outcome": {"kind": "grounded_tool_answer", "authoritative_facts": {"status": "processing"}},
        "requires_confirmation": False,
        "forbidden_actions": ("write", "cross_customer_disclosure"),
        "scenario_ids": ("54d93c0f-951e-5d74-afdd-80d33d4c8c95",),
    }
    data.update(overrides)
    return EvaluationCase.model_validate(data)


def test_evaluation_case_is_closed_and_immutable() -> None:
    case = make_case()
    assert str(case.scenario_ids[0]) == "54d93c0f-951e-5d74-afdd-80d33d4c8c95"
    with pytest.raises(ValidationError):
        EvaluationCase.model_validate({**case.model_dump(), "extra": True})
    with pytest.raises(ValidationError):
        case.case_id = "changed"


def test_evaluation_observation_contains_typed_tool_and_safety_data() -> None:
    observation = EvaluationObservation(
        observed_tools=(
            ObservedToolCall(
                tool_name="get_order_status",
                arguments={"order_id": "54d93c0f-951e-5d74-afdd-80d33d4c8c95"},
                result={"status": "processing"},
            ),
        ),
        final_response="Your order is processing.",
        authoritative_tool_results=({"status": "processing"},),
        answer_facts={"status": "processing"},
        safety=SafetyOutcome(),
        latency_ms=12.5,
        cost_usd=None,
        started_at=datetime.now(UTC),
    )
    assert observation.observed_tools[0].tool_name == "get_order_status"
    assert observation.safety.severity == "S0"
    assert observation.cost_usd is None


def test_metric_value_preserves_zero_denominator_as_not_applicable() -> None:
    metric = MetricValue(status="not_applicable", numerator=0, denominator=0)
    assert metric.value is None


def test_metric_value_rejects_negative_counts() -> None:
    with pytest.raises(ValidationError):
        MetricValue(status="available", numerator=-1, denominator=2)
