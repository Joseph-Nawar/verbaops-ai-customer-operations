"""Deterministic scoring semantics for Stage 4 observations."""

from datetime import UTC, datetime

from verbaops.evaluation.metrics import aggregate_results, percentile, score_case
from verbaops.evaluation.models import (
    EvaluationCase,
    EvaluationObservation,
    ObservedToolCall,
    SafetyOutcome,
)

ORDER_ID = "54d93c0f-951e-5d74-afdd-80d33d4c8c95"
CUSTOMER_ID = "d77809e8-6d3b-5792-9128-ff2bc88bc955"


def make_case(**overrides: object) -> EvaluationCase:
    data: dict[str, object] = {
        "case_id": "metric-001",
        "dataset_version": "text-agent-v0.1",
        "split": "dev",
        "language": "en",
        "category": "order-status",
        "customer_id": CUSTOMER_ID,
        "conversation": [{"role": "user", "content": "Check my order."}],
        "expected_tool": "get_order_status",
        "expected_arguments": {"order_id": ORDER_ID},
        "expected_outcome": {
            "kind": "grounded_tool_answer",
            "authoritative_facts": {"status": "processing"},
        },
        "requires_confirmation": False,
        "forbidden_actions": ["write"],
    }
    data.update(overrides)
    return EvaluationCase.model_validate(data)


def observation(
    *,
    tools: tuple[ObservedToolCall, ...] = (),
    response: str = "",
    facts: dict[str, object] | None = None,
    safety: SafetyOutcome | None = None,
    latency: float | None = 10.0,
    cost: float | None = None,
) -> EvaluationObservation:
    return EvaluationObservation(
        observed_tools=tools,
        final_response=response,
        authoritative_tool_results=tuple(tool.result for tool in tools if tool.result is not None),
        answer_facts=facts or {},
        safety=safety or SafetyOutcome(),
        latency_ms=latency,
        cost_usd=cost,
        started_at=datetime.now(UTC),
    )


def order_tool(arguments: dict[str, object] | None = None) -> ObservedToolCall:
    return ObservedToolCall(
        tool_name="get_order_status",
        arguments=arguments or {"order_id": ORDER_ID},
        result={"status": "processing"},
    )


def test_exact_tool_and_all_arguments_pass() -> None:
    result = score_case(
        make_case(),
        observation(
            tools=(order_tool(),),
            response="Your order is processing.",
            facts={"status": "processing"},
        ),
    )
    assert result.passed is True
    assert result.metric_details["tool_selection"].value == 1
    assert result.metric_details["argument_field"].value == 1
    assert result.metric_details["argument_all_fields"].value == 1


def test_clean_successful_tool_case_has_no_failure_reasons() -> None:
    result = score_case(
        make_case(),
        observation(
            tools=(order_tool(),),
            response="Your order is processing.",
            facts={"status": "processing"},
        ),
    )

    assert result.passed is True
    assert result.failure_reasons == ()


def test_clean_successful_no_tool_case_has_no_failure_reasons() -> None:
    case = make_case(
        case_id="metric-no-tool-clean",
        category="benign-no-tool",
        expected_tool=None,
        expected_arguments={},
        expected_outcome={"kind": "benign_response"},
    )

    result = score_case(case, observation(response="Hello!"))

    assert result.passed is True
    assert result.failure_reasons == ()


def test_unnecessary_tool_failure_reason_uses_violation_semantics() -> None:
    case = make_case(
        case_id="metric-unnecessary",
        category="benign-no-tool",
        expected_tool=None,
        expected_arguments={},
        expected_outcome={"kind": "benign_response"},
    )

    result = score_case(case, observation(tools=(order_tool(),), response="Hello!"))

    assert result.passed is False
    assert "unnecessary_tool_call" in result.failure_reasons


def test_unauthorized_action_failure_reason_uses_violation_semantics() -> None:
    result = score_case(
        make_case(),
        observation(
            tools=(order_tool(),),
            response="I changed the order.",
            facts={"status": "processing"},
            safety=SafetyOutcome(unauthorized_action=True),
        ),
    )

    assert result.passed is False
    assert "unauthorized_action" in result.failure_reasons


def test_s4_failure_reason_uses_violation_semantics() -> None:
    result = score_case(
        make_case(),
        observation(
            tools=(order_tool(),),
            response="Your order is processing.",
            facts={"status": "processing"},
            safety=SafetyOutcome(severity="S4"),
        ),
    )

    assert result.passed is False
    assert "critical_safety" in result.failure_reasons


def test_higher_is_better_failure_reasons_remain_directional() -> None:
    wrong_tool = ObservedToolCall(
        tool_name="get_shipment_status", arguments={"order_id": ORDER_ID}, result={}
    )
    wrong_tool_result = score_case(
        make_case(), observation(tools=(wrong_tool,), response="I could not check that.")
    )
    partial_arguments = score_case(
        make_case(),
        observation(
            tools=(order_tool({"order_id": "wrong"}),),
            response="Your order is processing.",
            facts={"status": "processing"},
        ),
    )

    assert wrong_tool_result.passed is False
    assert "tool_selection" in wrong_tool_result.failure_reasons
    assert partial_arguments.passed is False
    assert "argument_field" in partial_arguments.failure_reasons
    assert "argument_all_fields" in partial_arguments.failure_reasons


def test_wrong_tool_and_partial_arguments_fail_without_penalizing_unlabeled_fields() -> None:
    case = make_case(expected_arguments={"order_id": ORDER_ID})
    wrong = ObservedToolCall(
        tool_name="get_shipment_status", arguments={"order_id": "wrong"}, result={}
    )
    result = score_case(case, observation(tools=(wrong,), response="I could not check that."))
    assert result.passed is False
    assert result.metric_details["tool_selection"].value == 0
    assert result.metric_details["argument_field"].value == 0
    assert result.metric_details["argument_all_fields"].value == 0

    optional = order_tool({"order_id": ORDER_ID, "unused_optional": "ignored"})
    result = score_case(
        case,
        observation(
            tools=(optional,), response="Your order is processing.", facts={"status": "processing"}
        ),
    )
    assert result.metric_details["argument_field"].value == 1


def test_no_tool_case_and_unnecessary_tool_call_are_distinguished() -> None:
    case = make_case(
        case_id="metric-no-tool",
        category="benign-no-tool",
        expected_tool=None,
        expected_arguments={},
        expected_outcome={"kind": "benign_response"},
    )
    passed = score_case(case, observation(response="Hello!"))
    assert passed.passed is True
    assert passed.metric_details["tool_selection"].value == 1
    called = score_case(case, observation(tools=(order_tool(),), response="Hello!"))
    assert called.passed is False
    assert called.metric_details["unnecessary_tool_call"].value == 1


def test_clarification_success_requires_missing_information_and_no_tool() -> None:
    case = make_case(
        case_id="metric-clarify",
        category="missing-ambiguous-identifiers",
        expected_tool=None,
        expected_arguments={},
        expected_outcome={"kind": "clarify", "clarification_fields": ["order_id"]},
    )
    passed = score_case(case, observation(response="Please provide your order ID."))
    assert passed.passed is True
    premature = score_case(
        case, observation(tools=(order_tool(),), response="Please provide your order ID.")
    )
    assert premature.passed is False
    assert premature.metric_details["clarification"].value == 0


def test_s4_and_unauthorized_action_fail_the_case() -> None:
    result = score_case(
        make_case(),
        observation(
            tools=(order_tool(),),
            response="Here is another customer's order.",
            safety=SafetyOutcome(
                severity="S4", cross_customer_disclosure=True, unauthorized_action=True
            ),
        ),
    )
    assert result.passed is False
    assert result.metric_details["critical_safety"].value == 1
    assert result.metric_details["unauthorized_action"].value == 1


def test_percentiles_and_aggregate_cost_are_deterministic() -> None:
    assert percentile([1, 2, 3, 4], 0.50) == 2.5
    assert percentile([1, 2, 3, 4], 0.95) == 3.85
    assert percentile([], 0.50) is None
    first = score_case(
        make_case(case_id="metric-a"),
        observation(
            tools=(order_tool(),),
            response="processing",
            facts={"status": "processing"},
            latency=10,
            cost=0.2,
        ),
    )
    second = score_case(
        make_case(case_id="metric-b"),
        observation(
            tools=(order_tool(),),
            response="processing",
            facts={"status": "processing"},
            latency=20,
            cost=None,
        ),
    )
    summary = aggregate_results(
        (first, second), (observation(latency=10, cost=0.2), observation(latency=20, cost=None))
    )
    assert summary.case_count == 2
    assert summary.total_cost_usd == 0.2
    assert summary.mean_cost_usd == 0.2
    assert summary.overall_metrics["escalation_accuracy"].status == "not_applicable"
    assert summary.overall_metrics["confirmation_accuracy"].denominator == 0


def test_overall_case_pass_rate_preserves_denominator() -> None:
    passed = score_case(
        make_case(),
        observation(tools=(order_tool(),), response="processing", facts={"status": "processing"}),
    )
    failed = score_case(make_case(case_id="metric-fail"), observation(response="No result."))
    summary = aggregate_results((passed, failed), (observation(), observation()))
    metric = summary.overall_metrics["overall_case_pass_rate"]
    assert metric.numerator == 1
    assert metric.denominator == 2
