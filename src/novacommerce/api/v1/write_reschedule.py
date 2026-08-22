"""Authenticated shipment rescheduling route."""

from typing import Annotated
from uuid import UUID

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
from novacommerce.schemas.writes import RescheduleRequest
from novacommerce.services.writes.reschedule import reschedule_shipment

router = APIRouter(tags=["writes"])


@router.post("/orders/{order_id}/reschedule")
async def reschedule_order_route(
    order_id: UUID,
    request: RescheduleRequest,
    session: DatabaseSession,
    context: Annotated[TrustedCustomerContext, Depends(customer_dependency)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = validate_idempotency_key(idempotency_key)
    await require_customer(session, context)
    fingerprint = request_fingerprint(
        "shipment.reschedule",
        context.customer_id,
        target_ids=(order_id, request.delivery_slot_id),
        body=request,
    )
    execution = await execute_idempotent_write(
        session,
        key=key,
        operation="shipment.reschedule",
        customer_id=context.customer_id,
        fingerprint=fingerprint,
        operation_fn=lambda active_session: reschedule_shipment(
            active_session,
            customer_id=context.customer_id,
            order_id=order_id,
            request=request,
            idempotency_key=key,
        ),
    )
    return write_response(execution)
