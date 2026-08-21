"""Authenticated refund-request route."""

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
from novacommerce.schemas.writes import RefundCreateRequest
from novacommerce.services.writes.refunds import create_refund

router = APIRouter(tags=["writes"])


@router.post("/orders/{order_id}/refunds")
async def create_refund_route(
    order_id: UUID,
    request: RefundCreateRequest,
    session: DatabaseSession,
    context: Annotated[TrustedCustomerContext, Depends(customer_dependency)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = validate_idempotency_key(idempotency_key)
    await require_customer(session, context)
    fingerprint = request_fingerprint(
        "refund.request", context.customer_id, target_ids=(order_id,), body=request
    )
    execution = await execute_idempotent_write(
        session,
        key=key,
        operation="refund.request",
        customer_id=context.customer_id,
        fingerprint=fingerprint,
        operation_fn=lambda active_session: create_refund(
            active_session,
            customer_id=context.customer_id,
            order_id=order_id,
            request=request,
            idempotency_key=key,
        ),
    )
    return write_response(execution)
