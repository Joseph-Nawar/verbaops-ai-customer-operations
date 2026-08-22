"""Transactional support-ticket creation."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.db.models.order import Order
from novacommerce.db.models.support_ticket import SupportTicket, SupportTicketStatus
from novacommerce.idempotency import WriteOutcome
from novacommerce.schemas.writes import SupportTicketCreateRequest, SupportTicketResponse
from novacommerce.services.writes.common import append_event


async def create_ticket(
    session: AsyncSession,
    *,
    customer_id: UUID,
    request: SupportTicketCreateRequest,
    idempotency_key: str,
) -> WriteOutcome:
    if request.order_id is not None:
        order_id = (
            await session.execute(
                select(Order.id).where(
                    Order.id == request.order_id, Order.customer_id == customer_id
                )
            )
        ).scalar_one_or_none()
        if order_id is None:
            return WriteOutcome(
                404, {"error": {"code": "resource_not_found", "message": "Resource not found."}}
            )
    ticket = SupportTicket(
        id=uuid4(),
        customer_id=customer_id,
        order_id=request.order_id,
        subject=request.subject,
        description=request.description,
        status=SupportTicketStatus.OPEN,
    )
    session.add(ticket)
    await session.flush()
    await append_event(
        session,
        event_type="support_ticket.created",
        aggregate_type="support_ticket",
        aggregate_id=ticket.id,
        customer_id=customer_id,
        idempotency_key=idempotency_key,
        payload={
            "ticket_id": str(ticket.id),
            "order_id": str(request.order_id) if request.order_id else None,
        },
    )
    body = SupportTicketResponse(
        id=ticket.id,
        customer_id=ticket.customer_id,
        order_id=ticket.order_id,
        subject=ticket.subject,
        description=ticket.description,
        status=ticket.status,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )
    return WriteOutcome(201, body.model_dump(mode="json"))
