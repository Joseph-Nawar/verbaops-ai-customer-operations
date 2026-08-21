"""Authenticated order write routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy import select

from novacommerce.api.errors import APIError
from novacommerce.api.v1.dependencies import DatabaseSession, customer_dependency
from novacommerce.auth.context import TrustedCustomerContext
from novacommerce.db.models.customer import Customer
from novacommerce.idempotency import (
    execute_idempotent_write,
    request_fingerprint,
    validate_idempotency_key,
    write_response,
)
from novacommerce.schemas.writes import OrderCreateRequest
from novacommerce.services.writes.orders import cancel_order, create_order

router = APIRouter(tags=["writes"])


async def require_customer(session: DatabaseSession, context: TrustedCustomerContext) -> None:
    found = (
        await session.execute(select(Customer.id).where(Customer.id == context.customer_id))
    ).scalar_one_or_none()
    if found is None:
        await session.rollback()
        raise APIError(404, "resource_not_found", "Resource not found.")
    await session.rollback()


@router.post("/orders")
async def create_order_route(
    request: OrderCreateRequest,
    session: DatabaseSession,
    context: Annotated[TrustedCustomerContext, Depends(customer_dependency)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = validate_idempotency_key(idempotency_key)
    await require_customer(session, context)
    fingerprint = request_fingerprint("order.create", context.customer_id, body=request)
    execution = await execute_idempotent_write(
        session,
        key=key,
        operation="order.create",
        customer_id=context.customer_id,
        fingerprint=fingerprint,
        operation_fn=lambda active_session: create_order(
            active_session,
            customer_id=context.customer_id,
            request=request,
            idempotency_key=key,
        ),
    )
    return write_response(execution)


@router.post("/orders/{order_id}/cancel")
async def cancel_order_route(
    order_id: UUID,
    session: DatabaseSession,
    context: Annotated[TrustedCustomerContext, Depends(customer_dependency)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    key = validate_idempotency_key(idempotency_key)
    await require_customer(session, context)
    fingerprint = request_fingerprint(
        "order.cancel", context.customer_id, target_ids=(order_id,), body={}
    )
    execution = await execute_idempotent_write(
        session,
        key=key,
        operation="order.cancel",
        customer_id=context.customer_id,
        fingerprint=fingerprint,
        operation_fn=lambda active_session: cancel_order(
            active_session,
            customer_id=context.customer_id,
            order_id=order_id,
            idempotency_key=key,
        ),
    )
    return write_response(execution)
