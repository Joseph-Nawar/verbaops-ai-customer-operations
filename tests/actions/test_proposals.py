"""Provider-free M6C orchestration tests over the frozen M6A policy and repositories."""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

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
)
from verbaops.actions.proposals import ActionProposalService
from verbaops.actions.transitions import ActionEventType
from verbaops.auth.context import Role, TrustedContext
from verbaops.commerce.errors import CommerceNotFoundError
from verbaops.commerce.models import (
    DeliverySlotResponse,
    OrderItemResponse,
    OrderResponse,
    OrderStatus,
    RefundResponse,
    RefundStatus,
    ShipmentResponse,
    ShipmentStatus,
    TenantCurrencyResponse,
)
from verbaops.tools.stage6_models import MissingTrustedCustomerContextError

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
CUSTOMER_ID = UUID("20000000-0000-4000-8000-000000000002")
OTHER_CUSTOMER_ID = UUID("20000000-0000-4000-8000-000000000009")
PRINCIPAL_ID = UUID("60000000-0000-4000-8000-000000000006")
ORDER_ID = UUID("30000000-0000-4000-8000-000000000003")
SLOT_ID = UUID("40000000-0000-4000-8000-000000000004")
ITEM_ID = UUID("50000000-0000-4000-8000-000000000005")
INVOCATION_ID = UUID("90000000-0000-4000-8000-000000000009")
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def _context(
    roles: frozenset[Role] = frozenset({Role.CUSTOMER}),
    customer_id: UUID | None = CUSTOMER_ID,
) -> TrustedContext:
    return TrustedContext(
        principal_id=PRINCIPAL_ID,
        tenant_id=TENANT_ID,
        customer_id=customer_id,
        roles=roles,
    )


def _order(
    *,
    status: OrderStatus = OrderStatus.CONFIRMED,
    customer_id: UUID = CUSTOMER_ID,
    total: str = "1000.00",
) -> OrderResponse:
    return OrderResponse(
        id=ORDER_ID,
        customer_id=customer_id,
        status=status,
        total=total,
        created_at=NOW - timedelta(days=20),
        updated_at=NOW,
        items=[
            OrderItemResponse(
                order_item_id=ITEM_ID,
                product_id=uuid4(),
                sku="SKU-1",
                product_name="Item",
                quantity=2,
                unit_price="5.00",
                line_total="10.00",
            )
        ],
    )


def _shipment(
    *,
    status: ShipmentStatus = ShipmentStatus.PENDING,
    delivered_at: datetime | None = None,
) -> ShipmentResponse:
    return ShipmentResponse(
        id=uuid4(),
        order_id=ORDER_ID,
        carrier="Carrier",
        tracking_number=None,
        status=status,
        estimated_delivery=None,
        delivered_at=delivered_at,
        delivery_slot_id=None,
    )


class FakeCommerce:
    def __init__(self) -> None:
        self.order = _order()
        self.shipment: ShipmentResponse | None = _shipment()
        self.slots = [
            DeliverySlotResponse(
                id=SLOT_ID,
                service_date=NOW.date() + timedelta(days=1),
                window_start=time(9),
                window_end=time(11),
                capacity=5,
                reserved_count=1,
                remaining_capacity=4,
                available=True,
            )
        ]
        self.refunds: list[RefundResponse] = []
        self.currency: TenantCurrencyResponse | None = TenantCurrencyResponse(currency_code="USD")
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.order_not_found = False
        self.shipment_not_found = False

    async def get_order(self, order_id: UUID, customer_id: UUID) -> OrderResponse:
        self.calls.append(("get_order", (order_id, customer_id)))
        if self.order_not_found:
            raise CommerceNotFoundError()
        return self.order

    async def get_shipment(self, order_id: UUID, customer_id: UUID) -> ShipmentResponse:
        self.calls.append(("get_shipment", (order_id, customer_id)))
        if self.shipment_not_found or self.shipment is None:
            raise CommerceNotFoundError()
        return self.shipment

    async def list_delivery_slots(
        self, date_from: Any, date_to: Any, available_only: bool
    ) -> list[DeliverySlotResponse]:
        self.calls.append(("list_delivery_slots", (date_from, date_to, available_only)))
        return self.slots

    async def get_refunds(self, order_id: UUID, customer_id: UUID) -> list[RefundResponse]:
        self.calls.append(("get_refunds", (order_id, customer_id)))
        return self.refunds

    async def get_tenant_currency(self) -> TenantCurrencyResponse | None:
        self.calls.append(("get_tenant_currency", ()))
        return self.currency


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.record: Any = None

    async def create_or_get(self, **kwargs: Any) -> tuple[Any, bool]:
        self.calls.append(kwargs)
        if self.record is None:
            self.record = SimpleNamespace(
                id=uuid4(),
                action_type=kwargs["proposal"].action_type,
                proposal_fingerprint=kwargs["proposal_fingerprint"],
                originating_tool_invocation_id=kwargs["tool_invocation_id"],
                state=ActionState.PROPOSED,
                policy_allowed=None,
                policy_reason_code=None,
            )
        return self.record, len(self.calls) == 1


class FakeTransitions:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository
        self.calls: list[dict[str, Any]] = []

    async def transition(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        record = self.repository.record
        record.state = kwargs["target_state"]
        record.policy_allowed = kwargs["policy_decision"].allowed
        record.policy_reason_code = kwargs["policy_decision"].reason_code
        return record


def _service(
    commerce: FakeCommerce,
) -> tuple[ActionProposalService, FakeRepository, FakeTransitions]:
    repository = FakeRepository()
    transitions = FakeTransitions(repository)
    service = ActionProposalService(
        commerce,  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
        transitions,  # type: ignore[arg-type]
        now=lambda: NOW,
    )
    return service, repository, transitions


async def _propose(
    service: ActionProposalService,
    proposal: Any,
    *,
    context: TrustedContext | None = None,
) -> Any:
    return await service.propose(
        trusted_context=context or _context(),
        conversation_id=uuid4(),
        agent_run_id=uuid4(),
        tool_invocation_id=INVOCATION_ID,
        proposal=proposal,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("proposal", "order_status", "shipment_status", "expected_state"),
    [
        (
            RescheduleDeliveryProposal(order_id=ORDER_ID, delivery_slot_id=SLOT_ID),
            OrderStatus.SHIPPED,
            ShipmentStatus.IN_TRANSIT,
            ActionState.AWAITING_CONFIRMATION,
        ),
        (
            CancelOrderProposal(order_id=ORDER_ID),
            OrderStatus.CONFIRMED,
            ShipmentStatus.PENDING,
            ActionState.AWAITING_CONFIRMATION,
        ),
        (
            CancelOrderProposal(order_id=ORDER_ID),
            OrderStatus.PROCESSING,
            ShipmentStatus.PENDING,
            ActionState.AWAITING_APPROVAL,
        ),
        (
            CancelOrderProposal(order_id=ORDER_ID),
            OrderStatus.CONFIRMED,
            ShipmentStatus.LABEL_CREATED,
            ActionState.AWAITING_APPROVAL,
        ),
        (
            ReturnProposal(
                order_id=ORDER_ID,
                items=(ReturnItemProposal(order_item_id=ITEM_ID, quantity=1),),
                reason="Wrong size",
            ),
            OrderStatus.DELIVERED,
            ShipmentStatus.DELIVERED,
            ActionState.AWAITING_CONFIRMATION,
        ),
        (
            SupportTicketProposal(
                order_id=ORDER_ID,
                category=TicketCategory.ORDER,
                subject="Question",
                description="Please check this order.",
            ),
            OrderStatus.CONFIRMED,
            ShipmentStatus.PENDING,
            ActionState.AWAITING_CONFIRMATION,
        ),
        (
            RefundProposal(order_id=ORDER_ID, amount=Decimal("500.00"), reason="Refund"),
            OrderStatus.DELIVERED,
            ShipmentStatus.DELIVERED,
            ActionState.AWAITING_CONFIRMATION,
        ),
        (
            RefundProposal(order_id=ORDER_ID, amount=Decimal("500.01"), reason="Refund"),
            OrderStatus.DELIVERED,
            ShipmentStatus.DELIVERED,
            ActionState.AWAITING_APPROVAL,
        ),
    ],
)
async def test_frozen_action_gate_matrix_is_materialized_from_server_preflight(
    proposal: Any,
    order_status: OrderStatus,
    shipment_status: ShipmentStatus,
    expected_state: ActionState,
) -> None:
    commerce = FakeCommerce()
    commerce.order = _order(status=order_status)
    commerce.shipment = _shipment(
        status=shipment_status,
        delivered_at=NOW - timedelta(days=10)
        if shipment_status is ShipmentStatus.DELIVERED
        else None,
    )
    service, repository, transitions = _service(commerce)

    summary = await _propose(service, proposal)

    assert summary.state is expected_state
    assert summary.reason_code == "allowed"
    assert summary.required_next_actor == (
        "support_supervisor" if expected_state is ActionState.AWAITING_APPROVAL else "customer"
    )
    assert repository.calls[0]["tool_invocation_id"] == INVOCATION_ID
    assert repository.calls[0]["proposal_fingerprint"] == summary.proposal_fingerprint
    assert transitions.calls[0]["target_state"] is expected_state
    assert transitions.calls[0]["event_type"] is ActionEventType.POLICY_ALLOWED
    assert "Wrong size" not in summary.safe_summary
    assert "Please check this order." not in summary.safe_summary


@pytest.mark.asyncio
async def test_refund_without_canonical_currency_is_persisted_as_policy_denied() -> None:
    commerce = FakeCommerce()
    commerce.order = _order(status=OrderStatus.DELIVERED)
    commerce.currency = None
    service, repository, transitions = _service(commerce)

    summary = await _propose(
        service,
        RefundProposal(order_id=ORDER_ID, amount=Decimal("25.00"), reason="Duplicate charge"),
    )

    assert summary.state is ActionState.POLICY_DENIED
    assert summary.reason_code == "canonical_currency_unavailable"
    assert repository.calls[0]["tool_invocation_id"] == INVOCATION_ID
    assert transitions.calls[0]["event_type"] is ActionEventType.POLICY_DENIED


@pytest.mark.asyncio
async def test_support_customer_scope_role_matrix_uses_frozen_policy() -> None:
    proposal = CancelOrderProposal(order_id=ORDER_ID)
    bound_support = _context(frozenset({Role.SUPPORT_AGENT}))
    support_commerce = FakeCommerce()
    support_service, _, _ = _service(support_commerce)
    assert (await _propose(support_service, proposal, context=bound_support)).state is (
        ActionState.AWAITING_CONFIRMATION
    )

    for role in (Role.SUPPORT_AGENT,):
        unbound = _context(frozenset({role}), customer_id=None)
        commerce = FakeCommerce()
        service, repository, _ = _service(commerce)
        with pytest.raises(MissingTrustedCustomerContextError):
            await _propose(service, proposal, context=unbound)
        assert commerce.calls == []
        assert repository.calls == []

    for roles in (
        frozenset({Role.SUPPORT_SUPERVISOR}),
        frozenset({Role.TENANT_ADMIN}),
    ):
        commerce = FakeCommerce()
        service, _, _ = _service(commerce)
        denied = await _propose(service, proposal, context=_context(roles))
        assert (denied.state, denied.reason_code) == (
            ActionState.POLICY_DENIED,
            "proposal_role_not_allowed",
        )


@pytest.mark.asyncio
async def test_mismatched_commerce_owner_is_denied_by_frozen_policy() -> None:
    commerce = FakeCommerce()
    commerce.order = _order(customer_id=OTHER_CUSTOMER_ID)
    service, _, transitions = _service(commerce)

    summary = await _propose(service, CancelOrderProposal(order_id=ORDER_ID))

    assert (summary.state, summary.reason_code) == (
        ActionState.POLICY_DENIED,
        "customer_scope_mismatch",
    )
    assert len(commerce.calls) == 1
    assert transitions.calls[0]["policy_decision"].reason_code == "customer_scope_mismatch"


@pytest.mark.asyncio
async def test_missing_order_is_a_durable_ineligible_policy_denial() -> None:
    commerce = FakeCommerce()
    commerce.order_not_found = True
    service, repository, transitions = _service(commerce)

    summary = await _propose(service, CancelOrderProposal(order_id=ORDER_ID))

    assert (summary.state, summary.reason_code) == (
        ActionState.POLICY_DENIED,
        "commerce_ineligible",
    )
    assert len(repository.calls) == 1
    assert transitions.calls[0]["event_type"] is ActionEventType.POLICY_DENIED


@pytest.mark.asyncio
async def test_return_preflight_rejects_unowned_items_and_stale_delivery() -> None:
    proposal = ReturnProposal(
        order_id=ORDER_ID,
        items=(ReturnItemProposal(order_item_id=uuid4(), quantity=1),),
        reason="Wrong item",
    )
    commerce = FakeCommerce()
    commerce.order = _order(status=OrderStatus.DELIVERED)
    commerce.shipment = _shipment(
        status=ShipmentStatus.DELIVERED,
        delivered_at=NOW - timedelta(days=31),
    )
    service, _, transitions = _service(commerce)

    summary = await _propose(service, proposal)

    assert summary.state is ActionState.POLICY_DENIED
    assert summary.reason_code == "commerce_ineligible"
    assert transitions.calls[0]["policy_decision"].allowed is False


@pytest.mark.asyncio
async def test_refund_preflight_counts_only_committed_refund_states() -> None:
    commerce = FakeCommerce()
    commerce.order = _order(status=OrderStatus.DELIVERED)
    commerce.refunds = [
        RefundResponse(
            id=uuid4(),
            amount="600.00",
            status=RefundStatus.COMPLETED,
            reason="Prior refund",
            requires_manual_approval=False,
            created_at=NOW - timedelta(days=1),
        ),
        RefundResponse(
            id=uuid4(),
            amount="200.00",
            status=RefundStatus.REJECTED,
            reason="Rejected refund",
            requires_manual_approval=False,
            created_at=NOW - timedelta(days=1),
        ),
    ]
    allowed_service, _, _ = _service(commerce)
    denied_service, _, _ = _service(commerce)

    allowed = await _propose(
        allowed_service,
        RefundProposal(order_id=ORDER_ID, amount=Decimal("400.00"), reason="Remaining amount"),
    )
    denied = await _propose(
        denied_service,
        RefundProposal(order_id=ORDER_ID, amount=Decimal("400.01"), reason="Too much"),
    )

    assert allowed.state is ActionState.AWAITING_CONFIRMATION
    assert (denied.state, denied.reason_code) == (
        ActionState.POLICY_DENIED,
        "commerce_ineligible",
    )


@pytest.mark.asyncio
async def test_ticket_without_order_skips_commerce_reads_and_omits_user_text_from_summary() -> None:
    commerce = FakeCommerce()
    service, _, _ = _service(commerce)

    summary = await _propose(
        service,
        SupportTicketProposal(
            category=TicketCategory.OTHER,
            subject="Sensitive subject text",
            description="Sensitive ticket body",
        ),
    )

    assert summary.state is ActionState.AWAITING_CONFIRMATION
    assert "Sensitive" not in summary.safe_summary
    assert commerce.calls == []
