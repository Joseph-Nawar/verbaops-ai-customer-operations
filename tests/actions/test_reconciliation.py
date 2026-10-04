"""Serialized, same-key reconciliation behavior for unresolved action requests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from verbaops.actions.models import (
    ActionState,
    CancelOrderProposal,
    RefundProposal,
    RescheduleDeliveryProposal,
    ReturnItemProposal,
    ReturnProposal,
    SupportTicketProposal,
    TicketCategory,
    proposal_target_ids,
)
from verbaops.actions.reconciliation import ActionReconciler
from verbaops.auth.context import Role, TrustedContext
from verbaops.commerce.client import CommerceWriteResult
from verbaops.commerce.errors import (
    CommerceNotFoundError,
    CommerceWriteAmbiguousError,
    CommerceWriteRejected,
)
from verbaops.commerce.models import (
    OrderResponse,
    OrderStatus,
    RefundResponse,
    RefundStatus,
    ReturnItemResponse,
    ReturnResponse,
    ReturnStatus,
    ShipmentResponse,
    ShipmentStatus,
    SupportTicketCategory,
    SupportTicketResponse,
    SupportTicketStatus,
    WriteRefundResponse,
)

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


class FakeTransitions:
    def __init__(self, record: SimpleNamespace) -> None:
        self.record = record
        self._claim_lock = asyncio.Lock()
        self.lease_owner = None
        self.claim_count = 0
        self.finish_calls: list[dict[str, object]] = []

    async def get_scoped(self, action_id, tenant_id, customer_id):
        if (
            action_id != self.record.id
            or tenant_id != self.record.tenant_id
            or customer_id != self.record.customer_id
        ):
            from verbaops.actions.transitions import ActionRequestNotFoundError

            raise ActionRequestNotFoundError("action request not found in customer scope")
        return self.record

    async def claim_reconciliation(self, action_id, tenant_id, customer_id, expected_fingerprint):
        async with self._claim_lock:
            self.claim_count += 1
            if (
                action_id != self.record.id
                or tenant_id != self.record.tenant_id
                or customer_id != self.record.customer_id
                or expected_fingerprint != self.record.proposal_fingerprint
                or self.record.state is not ActionState.UNRESOLVED
                or self.lease_owner is not None
            ):
                return SimpleNamespace(record=self.record, lease_owner=None, claimed=False)
            self.lease_owner = uuid4()
            return SimpleNamespace(
                record=self.record,
                lease_owner=self.lease_owner,
                claimed=True,
            )

    async def record_reconciliation_outcome(
        self, *_args: object, **kwargs: object
    ) -> SimpleNamespace:
        self.finish_calls.append(kwargs)
        self.record.state = kwargs["target_state"]
        if "resource_id" in kwargs and kwargs["resource_id"] is not None:
            self.record.commerce_resource_id = kwargs["resource_id"]
        if "status_code" in kwargs:
            self.record.commerce_status_code = kwargs["status_code"]
        if "error_code" in kwargs:
            self.record.commerce_error_code = kwargs["error_code"]
        self.lease_owner = None
        return self.record


class ScriptedCommerce:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.orders: list[object] = []
        self.shipments: list[object] = []
        self.returns: dict[object, object] = {}
        self.tickets: dict[object, object] = {}
        self.refunds: list[object] = []
        self.write_results: dict[str, list[object]] = {}

    async def get_order(self, order_id, customer_id):
        self.calls.append(("get_order", (order_id, customer_id)))
        outcome = self.orders.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def get_shipment(self, order_id, customer_id):
        self.calls.append(("get_shipment", (order_id, customer_id)))
        outcome = self.shipments.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def get_return(self, resource_id, customer_id):
        self.calls.append(("get_return", (resource_id, customer_id)))
        outcome = self.returns[resource_id]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def get_support_ticket(self, resource_id, customer_id):
        self.calls.append(("get_support_ticket", (resource_id, customer_id)))
        outcome = self.tickets[resource_id]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def get_refunds(self, order_id, customer_id):
        self.calls.append(("get_refunds", (order_id, customer_id)))
        return self.refunds

    async def cancel_order(self, *args):
        return await self._write("cancel_order", args)

    async def reschedule_delivery(self, *args):
        return await self._write("reschedule_delivery", args)

    async def create_return(self, *args):
        return await self._write("create_return", args)

    async def create_support_ticket(self, *args):
        return await self._write("create_support_ticket", args)

    async def request_refund(self, *args):
        return await self._write("request_refund", args)

    async def _write(self, name: str, args: tuple[object, ...]):
        self.calls.append((name, args))
        outcome = self.write_results[name].pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def customer_context(*, tenant_id=None, customer_id=None, roles=None) -> TrustedContext:
    return TrustedContext(
        principal_id=uuid4(),
        tenant_id=tenant_id or uuid4(),
        customer_id=customer_id or uuid4(),
        roles=roles or frozenset({Role.CUSTOMER}),
    )


def action_record(proposal, context, *, resource_id=None, state=ActionState.UNRESOLVED):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=context.tenant_id,
        customer_id=context.customer_id,
        proposing_principal_id=context.principal_id,
        action_type=proposal.action_type,
        proposal_payload=proposal.model_dump(mode="json"),
        target_ids=proposal_target_ids(proposal),
        proposal_schema_version="action-proposal-v1",
        proposal_fingerprint="a" * 64,
        state=state,
        idempotency_key=uuid4(),
        commerce_resource_id=resource_id,
        commerce_status_code=None,
        commerce_error_code=None,
        verification_status=None,
        execution_lease_owner=None,
    )


def order_response(order_id, customer_id, status=OrderStatus.CANCELLED):
    return OrderResponse(
        id=order_id,
        customer_id=customer_id,
        status=status,
        total="50.00",
        created_at=NOW,
        updated_at=NOW,
        items=[],
    )


def shipment_response(order_id, *, slot_id=None, status=ShipmentStatus.CANCELLED):
    return ShipmentResponse(
        id=uuid4(),
        order_id=order_id,
        carrier="Carrier",
        tracking_number=None,
        status=status,
        estimated_delivery=None,
        delivered_at=None,
        delivery_slot_id=slot_id,
    )


def ticket_response(proposal, customer_id, ticket_id):
    return SupportTicketResponse(
        id=ticket_id,
        customer_id=customer_id,
        order_id=proposal.order_id,
        category=SupportTicketCategory(proposal.category.value),
        subject=proposal.subject,
        description=proposal.description,
        status=SupportTicketStatus.OPEN,
        created_at=NOW,
        updated_at=NOW,
    )


def write_result(response, status_code=201):
    return CommerceWriteResult(response, status_code, False)


@pytest.mark.asyncio
async def test_known_cancel_target_reads_exact_state_before_any_same_key_replay() -> None:
    context = customer_context()
    order_id = uuid4()
    proposal = CancelOrderProposal(order_id=order_id)
    action = action_record(proposal, context, resource_id=order_id)
    transitions = FakeTransitions(action)
    commerce = ScriptedCommerce()
    commerce.orders = [order_response(order_id, context.customer_id)]
    commerce.shipments = [CommerceNotFoundError()]
    commerce.write_results["cancel_order"] = []
    reconciler = ActionReconciler(commerce_client=commerce, transition_service=transitions)

    result = await reconciler.reconcile(action.id, context)

    assert result.state is ActionState.SUCCEEDED
    assert [call[0] for call in commerce.calls] == ["get_order", "get_shipment"]
    assert transitions.finish_calls[-1]["verified_resource_id"] == order_id


@pytest.mark.asyncio
async def test_stale_reschedule_readback_precedes_identical_same_key_replay() -> None:
    context = customer_context()
    order_id, target_slot, old_slot = uuid4(), uuid4(), uuid4()
    proposal = RescheduleDeliveryProposal(order_id=order_id, delivery_slot_id=target_slot)
    action = action_record(proposal, context, resource_id=uuid4())
    transitions = FakeTransitions(action)
    commerce = ScriptedCommerce()
    stale_shipment = shipment_response(order_id, slot_id=old_slot, status=ShipmentStatus.IN_TRANSIT)
    current_shipment = shipment_response(
        order_id, slot_id=target_slot, status=ShipmentStatus.IN_TRANSIT
    )
    commerce.shipments = [stale_shipment, current_shipment]
    commerce.write_results["reschedule_delivery"] = [write_result(current_shipment, 200)]
    reconciler = ActionReconciler(commerce_client=commerce, transition_service=transitions)

    result = await reconciler.reconcile(action.id, context)

    assert result.state is ActionState.SUCCEEDED
    assert [call[0] for call in commerce.calls] == [
        "get_shipment",
        "reschedule_delivery",
        "get_shipment",
    ]
    write_call = commerce.calls[1][1]
    assert write_call[-1] == action.idempotency_key


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["return", "ticket", "refund"])
async def test_created_resource_without_id_replays_first_with_same_key_then_reads_exact_id(
    kind: str,
) -> None:
    context = customer_context()
    if kind == "return":
        item_id, order_id, return_id = uuid4(), uuid4(), uuid4()
        proposal = ReturnProposal(
            order_id=order_id,
            reason="damaged",
            items=(ReturnItemProposal(order_item_id=item_id, quantity=1),),
        )
        response = ReturnResponse(
            id=return_id,
            order_id=order_id,
            reason="damaged",
            status=ReturnStatus.REQUESTED,
            created_at=NOW,
            updated_at=NOW,
            items=[ReturnItemResponse(id=uuid4(), order_item_id=item_id, quantity=1)],
        )
        read_method, write_method = "get_return", "create_return"
    elif kind == "ticket":
        proposal = SupportTicketProposal(
            order_id=None,
            category=TicketCategory.OTHER,
            subject="Need help",
            description="Please help",
        )
        return_id = uuid4()
        response = ticket_response(proposal, context.customer_id, return_id)
        read_method, write_method = "get_support_ticket", "create_support_ticket"
    else:
        order_id, return_id = uuid4(), uuid4()
        proposal = RefundProposal(order_id=order_id, amount=Decimal("25.00"), reason="damaged")
        response = WriteRefundResponse(
            id=return_id,
            amount=Decimal("25.00"),
            status=RefundStatus.APPROVED,
            reason="damaged",
            requires_manual_approval=False,
            created_at=NOW,
        )
        read_method, write_method = "get_refunds", "request_refund"

    action = action_record(proposal, context, resource_id=None)
    transitions = FakeTransitions(action)
    commerce = ScriptedCommerce()
    commerce.write_results[write_method] = [write_result(response)]
    if kind == "return":
        commerce.returns[return_id] = response
    elif kind == "ticket":
        commerce.tickets[return_id] = response
    else:
        commerce.refunds = [
            RefundResponse(
                id=return_id,
                amount="25.00",
                status=RefundStatus.APPROVED,
                reason="damaged",
                requires_manual_approval=False,
                created_at=NOW,
            )
        ]
    reconciler = ActionReconciler(commerce_client=commerce, transition_service=transitions)

    result = await reconciler.reconcile(action.id, context)

    assert result.state is ActionState.SUCCEEDED
    names = [call[0] for call in commerce.calls]
    assert names == [write_method, read_method]
    assert commerce.calls[0][1][-1] == action.idempotency_key
    assert result.commerce_resource_id == return_id


@pytest.mark.asyncio
async def test_known_created_resource_is_read_before_replay_and_mismatch_stays_unresolved() -> None:
    context = customer_context()
    ticket_id = uuid4()
    proposal = SupportTicketProposal(
        order_id=None,
        category=TicketCategory.OTHER,
        subject="Need help",
        description="Original",
    )
    action = action_record(proposal, context, resource_id=ticket_id)
    transitions = FakeTransitions(action)
    commerce = ScriptedCommerce()
    commerce.tickets[ticket_id] = ticket_response(
        proposal.model_copy(update={"description": "Different"}),
        context.customer_id,
        ticket_id,
    )
    commerce.write_results["create_support_ticket"] = []
    reconciler = ActionReconciler(commerce_client=commerce, transition_service=transitions)

    result = await reconciler.reconcile(action.id, context)

    assert result.state is ActionState.UNRESOLVED
    assert [call[0] for call in commerce.calls] == ["get_support_ticket"]
    assert result.idempotency_key == action.idempotency_key


@pytest.mark.asyncio
async def test_replay_definite_rejection_fails_and_ambiguous_replay_stays_unresolved() -> None:
    for rejection in (
        CommerceWriteRejected(status_code=409, error_code="return_not_allowed"),
        CommerceWriteAmbiguousError(status_code=None, error_code=None),
    ):
        context = customer_context()
        order_id, item_id = uuid4(), uuid4()
        proposal = ReturnProposal(
            order_id=order_id,
            reason="damaged",
            items=(ReturnItemProposal(order_item_id=item_id, quantity=1),),
        )
        action = action_record(proposal, context)
        transitions = FakeTransitions(action)
        commerce = ScriptedCommerce()
        commerce.write_results["create_return"] = [rejection]
        reconciler = ActionReconciler(commerce_client=commerce, transition_service=transitions)

        result = await reconciler.reconcile(action.id, context)

        expected_state = (
            ActionState.FAILED
            if isinstance(rejection, CommerceWriteRejected)
            else ActionState.UNRESOLVED
        )
        assert result.state is expected_state
        assert [call[0] for call in commerce.calls] == ["create_return"]
        assert commerce.calls[0][1][-1] == action.idempotency_key


@pytest.mark.asyncio
async def test_cross_customer_reconciliation_is_not_found_and_never_calls_commerce() -> None:
    context = customer_context()
    proposal = SupportTicketProposal(
        order_id=None,
        category=TicketCategory.OTHER,
        subject="Need help",
        description="Please help",
    )
    action = action_record(proposal, context)
    transitions = FakeTransitions(action)
    commerce = ScriptedCommerce()
    reconciler = ActionReconciler(commerce_client=commerce, transition_service=transitions)

    from verbaops.actions.transitions import ActionRequestNotFoundError

    with pytest.raises(ActionRequestNotFoundError):
        await reconciler.reconcile(action.id, customer_context(tenant_id=context.tenant_id))

    assert commerce.calls == []


@pytest.mark.asyncio
async def test_two_reconciliation_callers_can_claim_only_one_replay() -> None:
    context = customer_context()
    proposal = SupportTicketProposal(
        order_id=None,
        category=TicketCategory.OTHER,
        subject="Need help",
        description="Please help",
    )
    action = action_record(proposal, context)
    transitions = FakeTransitions(action)
    commerce = ScriptedCommerce()
    ticket_id = uuid4()
    response = ticket_response(proposal, context.customer_id, ticket_id)
    commerce.write_results["create_support_ticket"] = [write_result(response)]
    commerce.tickets[ticket_id] = response
    reconciler = ActionReconciler(commerce_client=commerce, transition_service=transitions)

    await asyncio.gather(
        reconciler.reconcile(action.id, context),
        reconciler.reconcile(action.id, context),
    )

    assert [name for name, _args in commerce.calls].count("create_support_ticket") == 1
    write = next(args for name, args in commerce.calls if name == "create_support_ticket")
    assert write[-1] == action.idempotency_key
