"""Customer-scoped exact support-ticket read-back."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from novacommerce.api.errors import APIError
from novacommerce.api.v1.dependencies import DatabaseSession, customer_dependency
from novacommerce.auth.context import TrustedCustomerContext
from novacommerce.db.models.support_ticket import SupportTicket
from novacommerce.schemas.writes import SupportTicketResponse

router = APIRouter(tags=["reads"])


@router.get("/support-tickets/{ticket_id}", response_model=SupportTicketResponse)
async def get_support_ticket(
    ticket_id: UUID,
    session: DatabaseSession,
    context: Annotated[TrustedCustomerContext, Depends(customer_dependency)],
) -> SupportTicketResponse:
    """Return one exact support ticket owned by the authenticated customer."""

    record = (
        await session.execute(
            select(SupportTicket).where(
                SupportTicket.id == ticket_id,
                SupportTicket.customer_id == context.customer_id,
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise APIError(404, "resource_not_found", "Resource not found.")
    return SupportTicketResponse.model_validate(record)
