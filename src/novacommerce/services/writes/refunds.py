"""Transactional refund requests without payment movement."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.db.models.order import Order, OrderStatus
from novacommerce.db.models.refund import Refund, RefundStatus
from novacommerce.idempotency import WriteOutcome
from novacommerce.schemas.writes import RefundCreateRequest, WriteRefundResponse
from novacommerce.services.writes.common import append_event
from novacommerce.services.writes.rules import refund_decision, remaining_refundable


def _error(code: str, message: str) -> WriteOutcome:
    return WriteOutcome(409, {"error": {"code": code, "message": message}})


async def create_refund(
    session: AsyncSession,
    *,
    customer_id: UUID,
    order_id: UUID,
    request: RefundCreateRequest,
    idempotency_key: str,
) -> WriteOutcome:
    order = (
        await session.execute(
            select(Order)
            .where(Order.id == order_id, Order.customer_id == customer_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if order is None:
        return WriteOutcome(
            404, {"error": {"code": "resource_not_found", "message": "Resource not found."}}
        )
    if order.status not in {OrderStatus.DELIVERED, OrderStatus.CANCELLED}:
        return _error("refund_not_allowed", "Refund is not allowed for this order.")
    committed = (
        await session.execute(
            select(Refund.amount).where(
                Refund.order_id == order.id,
                Refund.status.in_(
                    {
                        RefundStatus.APPROVED,
                        RefundStatus.PENDING_MANUAL_APPROVAL,
                        RefundStatus.COMPLETED,
                    }
                ),
            )
        )
    ).scalars()
    remaining = remaining_refundable(order.total, list(committed))
    if request.amount > remaining:
        return _error(
            "refund_amount_exceeds_remaining",
            "Refund amount exceeds the remaining refundable amount.",
        )
    status, manual = refund_decision(request.amount)
    refund = Refund(
        id=uuid4(),
        order_id=order.id,
        amount=request.amount,
        status=status,
        reason=request.reason,
        requires_manual_approval=manual,
    )
    session.add(refund)
    await session.flush()
    await append_event(
        session,
        event_type="refund.requested",
        aggregate_type="refund",
        aggregate_id=refund.id,
        customer_id=customer_id,
        idempotency_key=idempotency_key,
        payload={
            "refund_id": str(refund.id),
            "order_id": str(order.id),
            "amount": format(refund.amount, ".2f"),
        },
    )
    body = WriteRefundResponse(
        id=refund.id,
        amount=refund.amount,
        status=refund.status,
        reason=refund.reason,
        requires_manual_approval=refund.requires_manual_approval,
        created_at=refund.created_at,
    )
    return WriteOutcome(201, body.model_dump(mode="json"))
