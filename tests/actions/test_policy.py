"""Provider-free contracts for the frozen Stage 6 action policy."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from verbaops.actions.models import (
    ActionProposal,
    CancelOrderProposal,
    CommerceSnapshot,
    RefundProposal,
    RescheduleDeliveryProposal,
    ReturnItemProposal,
    ReturnProposal,
    SupportTicketProposal,
    TicketCategory,
)
from verbaops.auth.context import Role, TrustedContext
from verbaops.commerce.models import OrderStatus, ShipmentStatus

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
CUSTOMER_ID = UUID("20000000-0000-4000-8000-000000000002")
OTHER_CUSTOMER_ID = UUID("20000000-0000-4000-8000-000000000009")
ORDER_ID = UUID("30000000-0000-4000-8000-000000000003")
SLOT_ID = UUID("40000000-0000-4000-8000-000000000004")
ITEM_ID = UUID("50000000-0000-4000-8000-000000000005")
OBSERVED_AT = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
POLICY_VERSION = "stage6-policy-v1"


def _context(
    roles: frozenset[Role] = frozenset({Role.CUSTOMER}),
    customer_id: UUID | None = CUSTOMER_ID,
) -> TrustedContext:
    return TrustedContext(
        principal_id=UUID("60000000-0000-4000-8000-000000000006"),
        tenant_id=TENANT_ID,
        customer_id=customer_id,
        roles=roles,
    )


def _snapshot(
    *,
    customer_id: UUID = CUSTOMER_ID,
    order_id: UUID | None = ORDER_ID,
    order_status: OrderStatus | None = OrderStatus.CONFIRMED,
    shipment_status: ShipmentStatus | None = ShipmentStatus.PENDING,
    eligible: bool = True,
    fresh: bool = True,
) -> CommerceSnapshot:
    return CommerceSnapshot(
        customer_id=customer_id,
        order_id=order_id,
        order_status=order_status,
        shipment_status=shipment_status,
        eligible=eligible,
        fresh=fresh,
        observed_at=OBSERVED_AT,
        material_values={"order_status": order_status.value if order_status else None},
    )


def _proposals() -> tuple[ActionProposal, ...]:
    return (
        RescheduleDeliveryProposal(order_id=ORDER_ID, delivery_slot_id=SLOT_ID),
        CancelOrderProposal(order_id=ORDER_ID),
        ReturnProposal(
            order_id=ORDER_ID,
            items=(ReturnItemProposal(order_item_id=ITEM_ID, quantity=1),),
            reason="Wrong size",
        ),
        SupportTicketProposal(
            order_id=ORDER_ID,
            category=TicketCategory.ORDER,
            subject="Order update",
            description="Please check this order.",
        ),
        RefundProposal(order_id=ORDER_ID, amount=Decimal("500.00"), reason="Duplicate charge"),
    )


def _evaluate(
    trusted_context: TrustedContext,
    proposal: ActionProposal,
    snapshot: CommerceSnapshot,
    *,
    canonical_currency: str | None = "USD",
) -> Any:
    from verbaops.actions.policy import evaluate_action_policy

    return evaluate_action_policy(
        trusted_context=trusted_context,
        proposal=proposal,
        commerce_snapshot=snapshot,
        canonical_currency=canonical_currency,
        policy_version=POLICY_VERSION,
    )


def test_customer_scope_and_resource_ownership_come_from_trusted_context() -> None:
    decision = _evaluate(
        _context(customer_id=None), _proposals()[0], _snapshot(), canonical_currency="USD"
    )
    assert (decision.allowed, decision.reason_code, decision.confirmation_required) == (
        False,
        "customer_binding_required",
        False,
    )

    mismatched = _evaluate(
        _context(), _proposals()[0], _snapshot(customer_id=OTHER_CUSTOMER_ID)
    )
    assert (mismatched.allowed, mismatched.reason_code) == (False, "customer_scope_mismatch")

    wrong_order = _evaluate(
        _context(), _proposals()[0], _snapshot(order_id=UUID("30000000-0000-4000-8000-000000000009"))
    )
    assert (wrong_order.allowed, wrong_order.reason_code) == (False, "proposal_resource_mismatch")


def test_support_agent_and_supervisor_require_a_server_bound_customer() -> None:
    proposal = _proposals()[0]
    support_agent = _evaluate(
        _context(frozenset({Role.SUPPORT_AGENT})), proposal, _snapshot()
    )
    assert support_agent.allowed is True

    unbound_agent = _evaluate(
        _context(frozenset({Role.SUPPORT_AGENT}), customer_id=None), proposal, _snapshot()
    )
    assert (unbound_agent.allowed, unbound_agent.reason_code) == (
        False,
        "customer_binding_required",
    )

    supervisor_without_agent_authority = _evaluate(
        _context(frozenset({Role.SUPPORT_SUPERVISOR})), proposal, _snapshot()
    )
    assert supervisor_without_agent_authority.allowed is False

    bound_supervisor_agent = _evaluate(
        _context(frozenset({Role.SUPPORT_AGENT, Role.SUPPORT_SUPERVISOR})), proposal, _snapshot()
    )
    assert bound_supervisor_agent.allowed is True


def test_tenant_admin_alone_is_not_action_authority() -> None:
    decision = _evaluate(
        _context(frozenset({Role.TENANT_ADMIN})), _proposals()[0], _snapshot()
    )
    assert (decision.allowed, decision.reason_code) == (False, "proposal_role_not_allowed")


def test_every_supported_action_requires_customer_confirmation() -> None:
    for proposal in _proposals():
        decision = _evaluate(_context(), proposal, _snapshot())
        assert decision.allowed is True
        assert decision.confirmation_required is True
        assert decision.policy_version == POLICY_VERSION


def test_in_transit_reschedule_never_requires_supervisor_approval() -> None:
    decision = _evaluate(
        _context(),
        _proposals()[0],
        _snapshot(order_status=OrderStatus.SHIPPED, shipment_status=ShipmentStatus.IN_TRANSIT),
    )
    assert decision.allowed is True
    assert decision.confirmation_required is True
    assert decision.approval_required is False


@pytest.mark.parametrize(
    ("order_status", "shipment_status", "approval_required"),
    [
        (OrderStatus.PROCESSING, ShipmentStatus.PENDING, True),
        (OrderStatus.CONFIRMED, ShipmentStatus.LABEL_CREATED, True),
        (OrderStatus.PROCESSING, ShipmentStatus.LABEL_CREATED, True),
        (OrderStatus.CONFIRMED, ShipmentStatus.PENDING, False),
        (OrderStatus.SHIPPED, ShipmentStatus.IN_TRANSIT, False),
    ],
)
def test_cancellation_approval_matches_only_the_frozen_state_matrix(
    order_status: OrderStatus,
    shipment_status: ShipmentStatus,
    approval_required: bool,
) -> None:
    decision = _evaluate(
        _context(),
        _proposals()[1],
        _snapshot(order_status=order_status, shipment_status=shipment_status),
    )
    assert decision.allowed is True
    assert decision.confirmation_required is True
    assert decision.approval_required is approval_required


def test_return_and_ordinary_ticket_require_no_supervisor_approval() -> None:
    for proposal in (_proposals()[2], _proposals()[3]):
        decision = _evaluate(_context(), proposal, _snapshot())
        assert decision.allowed is True
        assert decision.confirmation_required is True
        assert decision.approval_required is False

    ticket_without_order = SupportTicketProposal(
        category=TicketCategory.DELIVERY,
        subject="Delivery question",
        description="Please share the delivery window.",
    )
    no_order_snapshot = _snapshot(order_id=None, order_status=None, shipment_status=None)
    ticket_decision = _evaluate(_context(), ticket_without_order, no_order_snapshot)
    assert ticket_decision.allowed is True
    assert ticket_decision.approval_required is False


def test_stale_or_ineligible_preflight_is_denied_before_confirmation() -> None:
    stale = _evaluate(_context(), _proposals()[0], _snapshot(fresh=False))
    assert (stale.allowed, stale.reason_code, stale.confirmation_required) == (
        False,
        "stale_snapshot",
        False,
    )

    ineligible = _evaluate(_context(), _proposals()[0], _snapshot(eligible=False))
    assert (ineligible.allowed, ineligible.reason_code) == (False, "commerce_ineligible")

    fresh = _evaluate(_context(), _proposals()[0], _snapshot(fresh=True))
    assert fresh.allowed is True


@pytest.mark.parametrize(
    ("amount", "approval_required"),
    [
        (Decimal("499.99"), False),
        (Decimal("500.00"), False),
        (Decimal("500.01"), True),
    ],
)
def test_refund_supervisor_threshold_is_strictly_greater_than_five_hundred(
    amount: Decimal, approval_required: bool
) -> None:
    proposal = RefundProposal(order_id=ORDER_ID, amount=amount, reason="Duplicate charge")
    decision = _evaluate(_context(), proposal, _snapshot(), canonical_currency="IQD")
    assert decision.allowed is True
    assert decision.confirmation_required is True
    assert decision.approval_required is approval_required


def test_missing_trusted_refund_currency_fails_closed_before_confirmation() -> None:
    decision = _evaluate(
        _context(), _proposals()[4], _snapshot(), canonical_currency=None
    )
    assert (decision.allowed, decision.reason_code, decision.confirmation_required) == (
        False,
        "canonical_currency_unavailable",
        False,
    )
