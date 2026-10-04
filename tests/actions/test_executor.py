"""RED-first tests for internal, claimed Commerce execution."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from verbaops.actions.executor import ActionExecutor
from verbaops.actions.models import ActionState, ActionType
from verbaops.actions.policy import PolicyDecision
from verbaops.commerce.errors import (
    CommerceWriteAmbiguousError,
    CommerceWritePreDispatchError,
    CommerceWriteRejected,
)
from verbaops.commerce.models import (
    CancelOrderResponse,
    OrderResponse,
    ShipmentResponse,
)


class FakeFreshness:
    def __init__(self, *, fingerprint: str = "a" * 64, allowed: bool = True) -> None:
        self.fingerprint = fingerprint
        self.allowed = allowed
        self.calls = 0

    async def refresh(self, _record: SimpleNamespace) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(
            proposal_fingerprint=self.fingerprint,
            policy_decision=PolicyDecision(
                allowed=self.allowed,
                reason_code="allowed" if self.allowed else "commerce_ineligible",
                confirmation_required=self.allowed,
                approval_required=False,
                policy_version="stage6-policy-v1",
            ),
        )


class FakeTransitions:
    def __init__(self, record: SimpleNamespace) -> None:
        self.record = record
        self.network_transaction_open = False
        self.claim_lock = asyncio.Lock()
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def get(self, _action_id: UUID) -> SimpleNamespace:
        return self.record

    async def claim_execution(self, *_args: object, **kwargs: object) -> SimpleNamespace:
        async with self.claim_lock:
            self.calls.append(("claim", kwargs))
            if self.record.state is not ActionState.READY_TO_EXECUTE:
                return SimpleNamespace(record=self.record, claimed=False)
            self.record.state = ActionState.EXECUTING
            self.record.execution_attempt_count += 1
            owner = uuid4()
            self.record.execution_lease_owner = owner
            self.network_transaction_open = False
            return SimpleNamespace(record=self.record, lease_owner=owner, claimed=True)

    async def record_execution_outcome(self, *_args: object, **kwargs: object) -> SimpleNamespace:
        self.calls.append(("outcome", kwargs))
        self.network_transaction_open = True
        self.record.state = kwargs["target_state"]
        self.record.commerce_status_code = kwargs.get("status_code")
        self.record.commerce_error_code = kwargs.get("error_code")
        self.record.commerce_resource_id = kwargs.get("resource_id")
        self.network_transaction_open = False
        return self.record

    async def transition(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(("transition", kwargs))
        self.record.state = kwargs["target_state"]
        return self.record


class ScriptedCommerce:
    def __init__(self, transitions: FakeTransitions, outcomes: list[object]) -> None:
        self.transitions = transitions
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    async def cancel_order(self, *args: object, **kwargs: object) -> object:
        assert not self.transitions.network_transaction_open
        self.calls.append(("cancel_order", args, kwargs))
        result = self.outcomes.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def action_record(
    *,
    state: ActionState = ActionState.READY_TO_EXECUTE,
    approval_required: bool = False,
    supervisor_approval_decision: str | None = None,
) -> SimpleNamespace:
    action_id, tenant_id, customer_id, order_id = (uuid4() for _ in range(4))
    return SimpleNamespace(
        id=action_id,
        tenant_id=tenant_id,
        customer_id=customer_id,
        proposing_principal_id=uuid4(),
        action_type=ActionType.CANCEL_ORDER,
        proposal_payload={"action_type": "cancel_order", "order_id": str(order_id)},
        target_ids=(order_id,),
        proposal_schema_version="action-proposal-v1",
        proposal_fingerprint="a" * 64,
        state=state,
        confirmation_required=True,
        approval_required=approval_required,
        customer_confirmation_decision="confirmed",
        customer_confirmation_fingerprint="a" * 64,
        supervisor_approval_decision=supervisor_approval_decision,
        policy_allowed=True,
        idempotency_key=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        execution_attempt_count=0,
        execution_lease_owner=None,
    )


def cancel_result(
    record: SimpleNamespace,
    *,
    status: str = "cancelled",
    shipment_status: str | None = None,
) -> SimpleNamespace:
    order_id = UUID(record.proposal_payload["order_id"])
    return SimpleNamespace(
        status_code=200,
        replayed=False,
        response=CancelOrderResponse(
            order=OrderResponse(
                id=order_id,
                customer_id=record.customer_id,
                status=status,
                total="20.00",
                created_at=datetime(2026, 10, 1, tzinfo=UTC),
                updated_at=datetime(2026, 10, 1, tzinfo=UTC),
                items=[],
            ),
            shipment=(
                ShipmentResponse(
                    id=uuid4(),
                    order_id=order_id,
                    carrier="Test Carrier",
                    tracking_number=None,
                    status=shipment_status,
                    estimated_delivery=None,
                    delivered_at=None,
                    delivery_slot_id=None,
                )
                if shipment_status is not None
                else None
            ),
        ),
    )


def executor_for(
    outcomes: list[object],
    *,
    record: SimpleNamespace | None = None,
    freshness: FakeFreshness | None = None,
) -> tuple[ActionExecutor, FakeTransitions, ScriptedCommerce, SimpleNamespace]:
    action = record or action_record()
    transitions = FakeTransitions(action)
    commerce = ScriptedCommerce(transitions, outcomes)
    executor = ActionExecutor(
        commerce_client=commerce,
        transition_service=transitions,
        freshness_service=freshness or FakeFreshness(),
    )
    return executor, transitions, commerce, action


@pytest.mark.asyncio
async def test_proven_pre_dispatch_retry_reuses_the_stored_idempotency_key() -> None:
    action = action_record()
    executor, _transitions, commerce, _ = executor_for(
        [CommerceWritePreDispatchError(), cancel_result(action)], record=action
    )

    result = await executor.execute_ready(action.id)

    assert len(commerce.calls) == 2
    assert commerce.calls[0][1:] == commerce.calls[1][1:]
    assert commerce.calls[0][1][2] == action.idempotency_key
    assert result.state is ActionState.UNRESOLVED  # exact read-back is added in M6D.2


@pytest.mark.asyncio
async def test_definite_rejection_is_failed_without_retry() -> None:
    action = action_record()
    executor, _transitions, commerce, _ = executor_for(
        [CommerceWriteRejected(status_code=409, error_code="order_not_cancellable")],
        record=action,
    )

    result = await executor.execute_ready(action.id)

    assert result.state is ActionState.FAILED
    assert len(commerce.calls) == 1


@pytest.mark.asyncio
async def test_post_dispatch_timeout_becomes_unresolved_without_automatic_replay() -> None:
    action = action_record()
    executor, transitions, commerce, _ = executor_for(
        [CommerceWriteAmbiguousError(status_code=None, error_code=None)], record=action
    )

    result = await executor.execute_ready(action.id)

    assert result.state is ActionState.UNRESOLVED
    assert len(commerce.calls) == 1
    assert transitions.calls[-1][1]["target_state"] is ActionState.UNRESOLVED


@pytest.mark.asyncio
async def test_contradictory_success_response_is_unresolved_not_succeeded() -> None:
    action = action_record()
    executor, _transitions, commerce, _ = executor_for(
        [cancel_result(action, status="confirmed")], record=action
    )

    result = await executor.execute_ready(action.id)

    assert result.state is ActionState.UNRESOLVED
    assert len(commerce.calls) == 1


@pytest.mark.asyncio
async def test_cancel_response_with_non_cancelled_shipment_is_unresolved() -> None:
    action = action_record()
    executor, _transitions, _commerce, _ = executor_for(
        [cancel_result(action, shipment_status="in_transit")], record=action
    )

    result = await executor.execute_ready(action.id)

    assert result.state is ActionState.UNRESOLVED


@pytest.mark.asyncio
async def test_freshness_mismatch_expires_before_dispatch() -> None:
    action = action_record()
    executor, transitions, commerce, _ = executor_for(
        [], record=action, freshness=FakeFreshness(fingerprint="b" * 64)
    )

    result = await executor.execute_ready(action.id)

    assert result.state is ActionState.EXPIRED
    assert len(commerce.calls) == 0
    assert transitions.calls[-1][1]["reason_code"] == "stale"


@pytest.mark.asyncio
async def test_fresh_policy_denial_prevents_dispatch() -> None:
    action = action_record()
    executor, transitions, commerce, _ = executor_for(
        [], record=action, freshness=FakeFreshness(allowed=False)
    )

    result = await executor.execute_ready(action.id)

    assert result.state is ActionState.POLICY_DENIED
    assert len(commerce.calls) == 0
    assert transitions.calls[-1][1]["policy_decision"].allowed is False


@pytest.mark.asyncio
async def test_unsatisfied_supervisor_gate_cannot_dispatch_even_if_state_is_corrupt() -> None:
    action = action_record(approval_required=True)
    executor, _transitions, commerce, _ = executor_for([], record=action)

    result = await executor.execute_ready(action.id)

    assert result.state is ActionState.READY_TO_EXECUTE
    assert len(commerce.calls) == 0


@pytest.mark.asyncio
async def test_two_execution_calls_cannot_dispatch_twice() -> None:
    action = action_record()
    executor, _transitions, commerce, _ = executor_for([cancel_result(action)], record=action)

    await asyncio.gather(
        executor.execute_ready(action.id),
        executor.execute_ready(action.id),
    )

    assert len(commerce.calls) == 1


@pytest.mark.asyncio
async def test_awaiting_approval_refund_cannot_reach_internal_write_dispatch() -> None:
    action = action_record(
        state=ActionState.AWAITING_APPROVAL,
        approval_required=True,
    )
    action.action_type = ActionType.REQUEST_REFUND
    action.proposal_payload = {
        "action_type": "request_refund",
        "order_id": str(uuid4()),
        "amount": "750.00",
        "reason": "customer request",
    }
    action.confirmation_required = True
    action.customer_confirmation_decision = None
    action.customer_confirmation_fingerprint = None
    executor, _transitions, commerce, _ = executor_for([], record=action)

    result = await executor.execute_ready(action.id)

    assert result.state is ActionState.AWAITING_APPROVAL
    assert len(commerce.calls) == 0


@pytest.mark.asyncio
async def test_locally_rejected_write_shape_fails_without_dispatch() -> None:
    action = action_record()
    order_id = str(action.target_ids[0])
    action.action_type = ActionType.REQUEST_REFUND
    action.proposal_payload = {
        "action_type": "request_refund",
        "order_id": order_id,
        "amount": "50.00",
        "reason": "r" * 501,
    }
    executor, transitions, commerce, _ = executor_for([], record=action)

    result = await executor.execute_ready(action.id)

    assert result.state is ActionState.FAILED
    assert len(commerce.calls) == 0
    assert transitions.calls[-1][1]["reason_code"] == "request_validation_rejected"
