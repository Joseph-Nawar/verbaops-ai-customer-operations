"""Authenticated support-ticket creation route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse

from novacommerce.api.v1.dependencies import DatabaseSession, customer_dependency
from novacommerce.api.v1.write_orders import require_customer
from novacommerce.auth.context import TrustedCustomerContext
from novacommerce.idempotency import (
    execute_idempotent_write,
    request_fingerprint,
    validate_idempotency_key,
    write_response,
)
from novacommerce.schemas.writes import SupportTicketCreateRequest
from novacommerce.services.writes.tickets import create_ticket

router = APIRouter(tags=["writes"])


@router.post("/support-tickets")
async def create_ticket_route(
    request: SupportTicketCreateRequest,
    session: DatabaseSession,
    context: Annotated[TrustedCustomerContext, Depends(customer_dependency)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = validate_idempotency_key(idempotency_key)
    await require_customer(session, context)
    fingerprint = request_fingerprint(
        "support_ticket.create",
        context.customer_id,
        target_ids=(request.order_id,) if request.order_id is not None else (),
        body=request,
    )
    execution = await execute_idempotent_write(
        session,
        key=key,
        operation="support_ticket.create",
        customer_id=context.customer_id,
        fingerprint=fingerprint,
        operation_fn=lambda active_session: create_ticket(
            active_session,
            customer_id=context.customer_id,
            request=request,
            idempotency_key=key,
        ),
    )
    return write_response(execution)
