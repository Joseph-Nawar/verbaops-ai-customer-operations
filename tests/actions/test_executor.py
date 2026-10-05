"""RED-first tests for internal, claimed Commerce execution."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest

from verbaops.actions.executor import ActionExecutor
from verbaops.actions.models import ActionState, ActionType
from verbaops.actions.policy import PolicyDecision
from verbaops.actions.proposals import ActionProposalService
from verbaops.actions.transitions import ActionTransitionService
from verbaops.commerce.client import CommerceClient
from verbaops.commerce.errors import (
    CommerceWriteAmbiguousError,
    CommerceWritePreDispatchError,
    CommerceWriteRejected,
)
from verbaops.commerce.models import (
    CancelOrderResponse,
    OrderResponse,
    OrderStatus,
    RefundApprovalReference,
    RefundResponse,
    RefundStatus,
    ShipmentResponse,
    ShipmentStatus,
    WriteRefundResponse,
)


class FakeFreshness:
    def __init__(
        self,
        *,
        fingerprint: str = "a" * 64,
        allowed: bool = True,
        approval: bool = False,
    ) -> None:
        self.fingerprint = fingerprint
        self.allowed = allowed
        self.approval = approval
        self.calls = 0

    async def refresh(self, _record: SimpleNamespace) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(
            proposal_fingerprint=self.fingerprint,
            policy_decision=PolicyDecision(
                allowed=self.allowed,
                reason_code="allowed" if self.allowed else "commerce_ineligible",
                confirmation_required=self.allowed,
                approval_required=self.approval,
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
        self.record.verified_resource_id = kwargs.get("verified_resource_id")
        self.record.verification_status = kwargs.get("verification_status")
        self.network_transaction_open = False
        return self.record

    async def record_execution_commerce_response(
        self, *_args: object, **kwargs: object
    ) -> SimpleNamespace:
        self.calls.append(("commerce_response", kwargs))
        self.network_transaction_open = True
        self.record.commerce_status_code = kwargs["status_code"]
        self.record.commerce_resource_id = kwargs["resource_id"]
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
        self.read_calls: list[tuple[str, tuple[object, ...]]] = []
        self.read_outcomes: dict[str, list[object]] = {}
        self.last_result: object | None = None

    async def cancel_order(self, *args: object, **kwargs: object) -> object:
        assert not self.transitions.network_transaction_open
        self.calls.append(("cancel_order", args, kwargs))
        result = self.outcomes.pop(0)
        if isinstance(result, BaseException):
            raise result
        self.last_result = result
        return result

    async def request_refund(self, *args: object, **kwargs: object) -> object:
        assert not self.transitions.network_transaction_open
        self.calls.append(("request_refund", args, kwargs))
        result = self.outcomes.pop(0)
        if isinstance(result, BaseException):
            raise result
        self.last_result = result
        return result

    async def get_order(self, *args: object) -> object:
        return await self._read("get_order", args, "order")

    async def get_shipment(self, *args: object) -> object:
        return await self._read("get_shipment", args, "shipment")

    async def get_refunds(self, *args: object) -> object:
        return await self._read("get_refunds", args, "refunds")

    async def _read(self, name: str, args: tuple[object, ...], field: str) -> object:
        assert not self.transitions.network_transaction_open
        self.read_calls.append((name, args))
        scripted = self.read_outcomes.get(name, [])
        outcome = (
            scripted.pop(0)
            if scripted
            else getattr(getattr(self.last_result, "response", None), field, None)
        )
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome is None:
            from verbaops.commerce.errors import CommerceNotFoundError

            raise CommerceNotFoundError()
        return outcome


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
    status: OrderStatus = OrderStatus.CANCELLED,
    shipment_status: ShipmentStatus | None = None,
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
        commerce_client=cast(CommerceClient, commerce),
        transition_service=cast(ActionTransitionService, transitions),
        freshness_service=cast(ActionProposalService, freshness or FakeFreshness()),
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
    assert result.state is ActionState.SUCCEEDED
    assert [call[0] for call in commerce.read_calls] == ["get_order"]


@pytest.mark.asyncio
async def test_second_proven_pre_dispatch_failure_is_terminal() -> None:
    action = action_record()
    executor, _transitions, commerce, _ = executor_for(
        [CommerceWritePreDispatchError(), CommerceWritePreDispatchError()], record=action
    )

    result = await executor.execute_ready(action.id)
    assert result.state is ActionState.FAILED
    retry = await executor.execute_ready(action.id)

    assert retry.state is ActionState.FAILED
    assert len(commerce.calls) == 2
    assert commerce.calls[0][1:] == commerce.calls[1][1:]
    assert commerce.calls[0][1][2] == action.idempotency_key


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
    assert commerce.read_calls == []
    assert transitions.calls[-1][1]["target_state"] is ActionState.UNRESOLVED


@pytest.mark.asyncio
async def test_contradictory_success_response_is_unresolved_not_succeeded() -> None:
    action = action_record()
    executor, _transitions, commerce, _ = executor_for(
        [cancel_result(action, status=OrderStatus.CONFIRMED)], record=action
    )

    result = await executor.execute_ready(action.id)

    assert result.state is ActionState.UNRESOLVED
    assert len(commerce.calls) == 1
    assert [call[0] for call in commerce.read_calls] == ["get_order"]


@pytest.mark.asyncio
async def test_cancel_response_with_non_cancelled_shipment_is_unresolved() -> None:
    action = action_record()
    executor, _transitions, commerce, _ = executor_for(
        [cancel_result(action, shipment_status=ShipmentStatus.IN_TRANSIT)], record=action
    )

    result = await executor.execute_ready(action.id)

    assert result.state is ActionState.UNRESOLVED
    assert [call[0] for call in commerce.read_calls] == ["get_order", "get_shipment"]


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
    decision = cast(PolicyDecision, transitions.calls[-1][1]["policy_decision"])
    assert decision.allowed is False


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

    results = await asyncio.gather(
        executor.execute_ready(action.id),
        executor.execute_ready(action.id),
    )

    assert len(commerce.calls) == 1
    assert any(result.state is ActionState.SUCCEEDED for result in results)


@pytest.mark.asyncio
async def test_readback_unavailable_is_unresolved_and_persists_verification_status() -> None:
    action = action_record()
    executor, transitions, commerce, _ = executor_for([cancel_result(action)], record=action)
    from verbaops.commerce.errors import CommerceUnavailableError

    commerce.read_outcomes["get_order"] = [CommerceUnavailableError()]

    result = await executor.execute_ready(action.id)

    assert result.state is ActionState.UNRESOLVED
    assert transitions.calls[-1][1]["verification_status"] == "unavailable"


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


def high_value_refund_action(*, actor_id: UUID | None = None) -> SimpleNamespace:
    action = action_record(
        approval_required=True,
        supervisor_approval_decision="approved",
    )
    order_id = UUID(action.proposal_payload["order_id"])
    action.action_type = ActionType.REQUEST_REFUND
    action.proposal_payload = {
        "action_type": "request_refund",
        "order_id": str(order_id),
        "amount": "750.00",
        "reason": "customer request",
    }
    action.target_ids = (order_id,)
    action.supervisor_approval_actor_id = actor_id or uuid4()
    action.supervisor_approval_fingerprint = action.proposal_fingerprint
    return action


def refund_result(action: SimpleNamespace) -> SimpleNamespace:
    refund_id = uuid4()
    return SimpleNamespace(
        status_code=201,
        replayed=False,
        response=WriteRefundResponse(
            id=refund_id,
            amount=Decimal("750.00"),
            status=RefundStatus.APPROVED,
            reason="customer request",
            requires_manual_approval=True,
            created_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
        refund_id=refund_id,
    )


@pytest.mark.asyncio
async def test_high_value_refund_dispatches_durable_approval_reference_and_verifies_manual_gate() -> (
    None
):
    action = high_value_refund_action()
    result = refund_result(action)
    executor, _transitions, commerce, _ = executor_for(
        [result], record=action, freshness=FakeFreshness(approval=True)
    )
    commerce.read_outcomes["get_refunds"] = [
        [
            RefundResponse(
                id=result.refund_id,
                amount="750.00",
                status=RefundStatus.APPROVED,
                reason="customer request",
                requires_manual_approval=True,
                created_at=datetime(2026, 10, 1, tzinfo=UTC),
            )
        ]
    ]

    completed = await executor.execute_ready(action.id)

    assert completed.state is ActionState.SUCCEEDED
    assert len(commerce.calls) == 1
    approval_reference = commerce.calls[0][1][3]
    assert isinstance(approval_reference, RefundApprovalReference)
    assert approval_reference.action_request_id == action.id
    assert approval_reference.proposal_fingerprint == action.proposal_fingerprint


@pytest.mark.asyncio
async def test_missing_durable_refund_approval_actor_blocks_dispatch() -> None:
    action = high_value_refund_action(actor_id=None)
    action.supervisor_approval_actor_id = None
    executor, _transitions, commerce, _ = executor_for(
        [], record=action, freshness=FakeFreshness(approval=True)
    )

    result = await executor.execute_ready(action.id)

    assert result.state is ActionState.READY_TO_EXECUTE
    assert commerce.calls == []
