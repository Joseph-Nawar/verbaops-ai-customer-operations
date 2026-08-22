"""Authenticated return-request route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse

from novacommerce.api.v1.dependencies import DatabaseSession, customer_dependency
from novacommerce.api.v1.metadata import write_openapi_extra
from novacommerce.api.v1.write_orders import require_customer
from novacommerce.auth.context import TrustedCustomerContext
from novacommerce.idempotency import (
    execute_idempotent_write,
    request_fingerprint,
    validate_idempotency_key,
    write_response,
)
from novacommerce.schemas.writes import ReturnCreateRequest, ReturnResponse
from novacommerce.services.writes.returns import create_return

router = APIRouter(tags=["writes"])


@router.post(
    "/returns",
    response_model=ReturnResponse,
    status_code=201,
    openapi_extra=write_openapi_extra(),
)
async def create_return_route(
    request: ReturnCreateRequest,
    session: DatabaseSession,
    context: Annotated[TrustedCustomerContext, Depends(customer_dependency)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", include_in_schema=False)
    ] = None,
) -> JSONResponse:
    key = validate_idempotency_key(idempotency_key)
    await require_customer(session, context)
    fingerprint = request_fingerprint(
        "return.create", context.customer_id, target_ids=(request.order_id,), body=request
    )
    execution = await execute_idempotent_write(
        session,
        key=key,
        operation="return.create",
        customer_id=context.customer_id,
        fingerprint=fingerprint,
        operation_fn=lambda active_session: create_return(
            active_session,
            customer_id=context.customer_id,
            request=request,
            idempotency_key=key,
        ),
    )
    return write_response(execution)
