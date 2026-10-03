"""Commerce preflight and deterministic orchestration for durable proposals."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from verbaops.actions.fingerprints import fingerprint_proposal
from verbaops.actions.models import (
    ActionProposal,
    ActionRequestSummary,
    ActionState,
    CancelOrderProposal,
    CommerceSnapshot,
    JSONValue,
    RefundProposal,
    RescheduleDeliveryProposal,
    ReturnProposal,
    SupportTicketProposal,
)
from verbaops.actions.policy import evaluate_action_policy
from verbaops.actions.repository import ActionRepository
from verbaops.actions.transitions import (
    ActionEventType,
    ActionExpiredError,
    ActionTransitionService,
)
from verbaops.auth.context import TrustedContext
from verbaops.commerce.client import CommerceClient
from verbaops.commerce.errors import CommerceNotFoundError, CommerceProtocolError
from verbaops.commerce.models import (
    OrderResponse,
    OrderStatus,
    RefundStatus,
    ShipmentResponse,
    ShipmentStatus,
)
from verbaops.tools.stage6_models import MissingTrustedCustomerContextError

ACTION_PROPOSAL_SCHEMA_VERSION = "action-proposal-v1"
ACTION_POLICY_VERSION = "stage6-policy-v1"
ACTION_PROPOSAL_TTL = timedelta(hours=24)
_REFUND_COUNTED_STATUSES = frozenset(
    {
        RefundStatus.APPROVED,
        RefundStatus.PENDING_MANUAL_APPROVAL,
        RefundStatus.COMPLETED,
    }
)
_CANCELLABLE_ORDER_STATUSES = frozenset(
    {OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.PROCESSING}
)
_CANCELLABLE_SHIPMENT_STATUSES = frozenset(
    {None, ShipmentStatus.PENDING, ShipmentStatus.LABEL_CREATED}
)
_RESCHEDULABLE_ORDER_STATUSES = frozenset(
    {OrderStatus.CONFIRMED, OrderStatus.PROCESSING, OrderStatus.SHIPPED}
)
_RESCHEDULABLE_SHIPMENT_STATUSES = frozenset(
    {ShipmentStatus.PENDING, ShipmentStatus.LABEL_CREATED, ShipmentStatus.IN_TRANSIT}
)


class ActionProposalService:
    """Read scoped Commerce facts, evaluate M6A policy, and persist proposal state."""

    def __init__(
        self,
        commerce_client: CommerceClient,
        action_repository: ActionRepository,
        transition_service: ActionTransitionService,
        *,
        policy_version: str = ACTION_POLICY_VERSION,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not policy_version.strip():
            raise ValueError("policy version must be non-empty")
        self._commerce = commerce_client
        self._repository = action_repository
        self._transitions = transition_service
        self._policy_version = policy_version
        self._now = now or (lambda: datetime.now(UTC))

    async def propose(
        self,
        *,
        trusted_context: TrustedContext,
        conversation_id: UUID,
        agent_run_id: UUID,
        tool_invocation_id: UUID,
        proposal: ActionProposal,
    ) -> ActionRequestSummary:
        """Preflight and durably create or resolve one model-proposed action."""

        if not isinstance(
            proposal,
            (
                RescheduleDeliveryProposal,
                CancelOrderProposal,
                ReturnProposal,
                SupportTicketProposal,
                RefundProposal,
            ),
        ):
            raise TypeError("proposal must be validated action data")
        if trusted_context.tenant_id != self._commerce.tenant_id:
            raise CommerceNotFoundError()
        customer_id = trusted_context.customer_id
        if customer_id is None:
            raise MissingTrustedCustomerContextError()

        snapshot, canonical_currency = await self._preflight(
            customer_id=customer_id,
            proposal=proposal,
        )
        decision = evaluate_action_policy(
            trusted_context=trusted_context,
            proposal=proposal,
            commerce_snapshot=snapshot,
            canonical_currency=canonical_currency,
            policy_version=self._policy_version,
        )
        action_type = proposal.action_type
        payload = proposal.model_dump(mode="python")
        material_values = dict(snapshot.material_values)
        if isinstance(proposal, RefundProposal):
            material_values["canonical_currency"] = canonical_currency
        fingerprint = fingerprint_proposal(
            tenant_id=trusted_context.tenant_id,
            customer_id=customer_id,
            action_type=action_type,
            schema_version=ACTION_PROPOSAL_SCHEMA_VERSION,
            target_ids=_target_ids(payload),
            normalized_payload=payload,
            material_snapshot=material_values,
        )

        record, _created = await self._repository.create_or_get(
            trusted_context=trusted_context,
            conversation_id=conversation_id,
            agent_run_id=agent_run_id,
            tool_invocation_id=tool_invocation_id,
            proposal=proposal,
            proposal_fingerprint=fingerprint,
            expires_at=self._now().astimezone(UTC) + ACTION_PROPOSAL_TTL,
        )
        if record.state is ActionState.PROPOSED:
            target_state = (
                ActionState.POLICY_DENIED
                if not decision.allowed
                else ActionState.AWAITING_APPROVAL
                if decision.approval_required
                else ActionState.AWAITING_CONFIRMATION
            )
            try:
                record = await self._transitions.transition(
                    action_request_id=record.id,
                    tenant_id=trusted_context.tenant_id,
                    expected_fingerprint=record.proposal_fingerprint,
                    target_state=target_state,
                    actor_id=trusted_context.principal_id,
                    event_type=(
                        ActionEventType.POLICY_ALLOWED
                        if decision.allowed
                        else ActionEventType.POLICY_DENIED
                    ),
                    reason_code=decision.reason_code,
                    policy_decision=decision,
                )
            except ActionExpiredError as error:
                if error.record is None:
                    raise
                record = error.record

        reason_code = record.policy_reason_code or decision.reason_code
        return ActionRequestSummary(
            action_request_id=record.id,
            action_type=record.action_type,
            state=record.state,
            proposal_fingerprint=record.proposal_fingerprint,
            safe_summary=_safe_summary(proposal, record.state, canonical_currency),
            required_next_actor=_required_next_actor(record.state),
            reason_code=reason_code,
        )

    async def _preflight(
        self,
        *,
        customer_id: UUID,
        proposal: ActionProposal,
    ) -> tuple[CommerceSnapshot, str | None]:
        now = self._now().astimezone(UTC)
        if isinstance(proposal, SupportTicketProposal) and proposal.order_id is None:
            return (
                CommerceSnapshot(
                    customer_id=customer_id,
                    eligible=True,
                    fresh=True,
                    observed_at=now,
                ),
                None,
            )

        order_id = proposal.order_id
        if order_id is None:
            raise TypeError("action proposal is missing its required order scope")
        try:
            order = await self._commerce.get_order(order_id, customer_id)
        except CommerceNotFoundError:
            return self._missing_order_snapshot(customer_id, order_id, now), None

        order_matches = order.id == order_id
        owner_matches = order.customer_id == customer_id
        if not order_matches or not owner_matches:
            snapshot = CommerceSnapshot(
                customer_id=order.customer_id,
                order_id=order.id,
                order_status=order.status,
                eligible=False,
                fresh=True,
                observed_at=now,
                material_values={
                    "order_status": order.status,
                    "resource_match": order_matches,
                    "customer_match": owner_matches,
                },
            )
            return snapshot, None

        if isinstance(proposal, RescheduleDeliveryProposal):
            return await self._preflight_reschedule(order, proposal, customer_id, now)
        if isinstance(proposal, CancelOrderProposal):
            return await self._preflight_cancellation(order, customer_id, now)
        if isinstance(proposal, ReturnProposal):
            return await self._preflight_return(order, proposal, customer_id, now)
        if isinstance(proposal, SupportTicketProposal):
            return (
                CommerceSnapshot(
                    customer_id=customer_id,
                    order_id=order.id,
                    order_status=order.status,
                    eligible=True,
                    fresh=True,
                    observed_at=now,
                    material_values={"order_status": order.status},
                ),
                None,
            )
        if isinstance(proposal, RefundProposal):
            return await self._preflight_refund(order, proposal, customer_id, now)
        raise TypeError(f"unsupported action proposal: {type(proposal).__name__}")

    async def _preflight_reschedule(
        self,
        order: OrderResponse,
        proposal: RescheduleDeliveryProposal,
        customer_id: UUID,
        now: datetime,
    ) -> tuple[CommerceSnapshot, None]:
        try:
            shipment = await self._commerce.get_shipment(order.id, customer_id)
        except CommerceNotFoundError:
            return self._snapshot(order, None, False, now, {"shipment_found": False}), None
        today = now.date()
        slots = await self._commerce.list_delivery_slots(
            today,
            today + timedelta(days=31),
            True,
        )
        slot = next((item for item in slots if item.id == proposal.delivery_slot_id), None)
        eligible = (
            shipment.order_id == order.id
            and order.status in _RESCHEDULABLE_ORDER_STATUSES
            and shipment.status in _RESCHEDULABLE_SHIPMENT_STATUSES
            and slot is not None
            and slot.available
            and slot.remaining_capacity > 0
            and slot.service_date >= today
        )
        material: dict[str, JSONValue] = {
            "order_status": order.status,
            "shipment_status": shipment.status,
            "current_delivery_slot_id": shipment.delivery_slot_id,
            "target_delivery_slot_id": proposal.delivery_slot_id,
            "target_available": slot.available if slot else None,
            "target_service_date": slot.service_date.isoformat() if slot else None,
            "target_window_start": slot.window_start.isoformat() if slot else None,
            "target_window_end": slot.window_end.isoformat() if slot else None,
            "target_remaining_capacity": slot.remaining_capacity if slot else None,
        }
        return self._snapshot(order, shipment, eligible, now, material), None

    async def _preflight_cancellation(
        self,
        order: OrderResponse,
        customer_id: UUID,
        now: datetime,
    ) -> tuple[CommerceSnapshot, None]:
        shipment: ShipmentResponse | None
        try:
            shipment = await self._commerce.get_shipment(order.id, customer_id)
        except CommerceNotFoundError:
            shipment = None
        eligible = (
            order.status in _CANCELLABLE_ORDER_STATUSES
            and (shipment is None or shipment.order_id == order.id)
            and (shipment.status if shipment is not None else None)
            in _CANCELLABLE_SHIPMENT_STATUSES
        )
        material = {
            "order_status": order.status,
            "shipment_status": shipment.status if shipment is not None else None,
            "shipment_order_match": (
                shipment.order_id == order.id if shipment is not None else None
            ),
        }
        return self._snapshot(order, shipment, eligible, now, material), None

    async def _preflight_return(
        self,
        order: OrderResponse,
        proposal: ReturnProposal,
        customer_id: UUID,
        now: datetime,
    ) -> tuple[CommerceSnapshot, None]:
        try:
            shipment = await self._commerce.get_shipment(order.id, customer_id)
        except CommerceNotFoundError:
            return self._snapshot(order, None, False, now, {"shipment_found": False}), None
        requested = {item.order_item_id: item.quantity for item in proposal.items}
        owned_items = {item.order_item_id: item.quantity for item in order.items}
        delivered_in_window = (
            shipment.delivered_at is not None
            and shipment.delivered_at.utcoffset() is not None
            and shipment.delivered_at.astimezone(UTC) >= now - timedelta(days=30)
            and shipment.delivered_at.astimezone(UTC) <= now
        )
        eligible = (
            order.status is OrderStatus.DELIVERED
            and shipment.order_id == order.id
            and shipment.status is ShipmentStatus.DELIVERED
            and delivered_in_window
            and all(
                item_id in owned_items and quantity <= owned_items[item_id]
                for item_id, quantity in requested.items()
            )
        )
        material = {
            "order_status": order.status,
            "shipment_status": shipment.status,
            "shipment_order_match": shipment.order_id == order.id,
            "delivered_at": shipment.delivered_at,
            "requested_items": [
                {
                    "order_item_id": item_id,
                    "requested_quantity": quantity,
                    "ordered_quantity": owned_items.get(item_id),
                }
                for item_id, quantity in sorted(requested.items(), key=lambda item: str(item[0]))
            ],
        }
        return self._snapshot(order, shipment, eligible, now, material), None

    async def _preflight_refund(
        self,
        order: OrderResponse,
        proposal: RefundProposal,
        customer_id: UUID,
        now: datetime,
    ) -> tuple[CommerceSnapshot, str | None]:
        refunds = await self._commerce.get_refunds(order.id, customer_id)
        currency_response = await self._commerce.get_tenant_currency()
        canonical_currency = (
            currency_response.currency_code if currency_response is not None else None
        )
        try:
            order_total = _commerce_money(order.total)
            refund_rows = [(refund.status, _commerce_money(refund.amount)) for refund in refunds]
        except (InvalidOperation, ValueError):
            raise CommerceProtocolError() from None
        already_committed = sum(
            (amount for status, amount in refund_rows if status in _REFUND_COUNTED_STATUSES),
            Decimal("0.00"),
        )
        remaining = order_total - already_committed
        eligible = (
            order.status in {OrderStatus.DELIVERED, OrderStatus.CANCELLED}
            and proposal.amount <= remaining
            and proposal.amount > 0
        )
        material: dict[str, JSONValue] = {
            "order_status": order.status,
            "order_total": order_total.quantize(Decimal("0.01")),
            "committed_refunds": already_committed.quantize(Decimal("0.01")),
            "remaining_refund_amount": remaining.quantize(Decimal("0.01")),
            "canonical_currency": canonical_currency,
        }
        return (
            CommerceSnapshot(
                customer_id=customer_id,
                order_id=order.id,
                order_status=order.status,
                eligible=eligible,
                fresh=True,
                observed_at=now,
                material_values=material,
            ),
            canonical_currency,
        )

    @staticmethod
    def _missing_order_snapshot(
        customer_id: UUID, order_id: UUID, observed_at: datetime
    ) -> CommerceSnapshot:
        return CommerceSnapshot(
            customer_id=customer_id,
            order_id=order_id,
            eligible=False,
            fresh=True,
            observed_at=observed_at,
            material_values={"commerce_resource_found": False},
        )

    @staticmethod
    def _snapshot(
        order: OrderResponse,
        shipment: ShipmentResponse | None,
        eligible: bool,
        observed_at: datetime,
        material_values: dict[str, Any],
    ) -> CommerceSnapshot:
        return CommerceSnapshot(
            customer_id=order.customer_id,
            order_id=order.id,
            order_status=order.status,
            shipment_status=shipment.status if shipment is not None else None,
            eligible=eligible,
            fresh=True,
            observed_at=observed_at,
            material_values=material_values,
        )


def _target_ids(payload: dict[str, Any]) -> tuple[UUID, ...]:
    found: set[UUID] = set()

    def visit(value: Any) -> None:
        if isinstance(value, UUID):
            found.add(value)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, (tuple, list)):
            for child in value:
                visit(child)

    visit(payload)
    return tuple(sorted(found, key=str))


def _commerce_money(value: str) -> Decimal:
    try:
        amount = Decimal(value)
        scaled = amount.quantize(Decimal("0.01"))
    except InvalidOperation:
        raise CommerceProtocolError() from None
    if not amount.is_finite() or amount < 0 or scaled != amount:
        raise CommerceProtocolError()
    return scaled


def _required_next_actor(
    state: ActionState,
) -> Literal["customer", "support_supervisor", "none"]:
    if state is ActionState.AWAITING_CONFIRMATION:
        return "customer"
    if state is ActionState.AWAITING_APPROVAL:
        return "support_supervisor"
    return "none"


def _safe_summary(
    proposal: ActionProposal,
    state: ActionState,
    canonical_currency: str | None,
) -> str:
    if state is ActionState.POLICY_DENIED:
        return "This proposal was denied by server policy or Commerce preflight."
    if isinstance(proposal, RescheduleDeliveryProposal):
        return f"Reschedule proposal for order {proposal.order_id} to slot {proposal.delivery_slot_id}."
    if isinstance(proposal, CancelOrderProposal):
        return f"Cancellation proposal for order {proposal.order_id}."
    if isinstance(proposal, ReturnProposal):
        return f"Return proposal for {len(proposal.items)} item(s) on order {proposal.order_id}."
    if isinstance(proposal, SupportTicketProposal):
        order = f" for order {proposal.order_id}" if proposal.order_id is not None else ""
        return f"Support ticket proposal in category {proposal.category.value}{order}."
    if isinstance(proposal, RefundProposal):
        currency = canonical_currency or "currency unavailable"
        amount = format(proposal.amount.quantize(Decimal("0.01")), ".2f")
        return f"Refund proposal for {amount} {currency} on order {proposal.order_id}."
    return "Action proposal recorded."
