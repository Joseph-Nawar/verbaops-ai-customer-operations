"""Customer-owned order, shipment, and refund read endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.api.dependencies import get_database_session
from novacommerce.api.errors import APIError
from novacommerce.api.v1.dependencies import customer_dependency
from novacommerce.api.v1.metadata import customer_openapi_extra
from novacommerce.auth.context import TrustedCustomerContext
from novacommerce.schemas.orders import OrderItemResponse, OrderResponse
from novacommerce.schemas.refunds import RefundResponse
from novacommerce.schemas.shipments import ShipmentResponse
from novacommerce.services.orders import get_owned_order, get_owned_refunds, get_owned_shipment

router = APIRouter(tags=["orders"])


@router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    openapi_extra=customer_openapi_extra(),
)
async def get_order(
    order_id: UUID,
    context: Annotated[TrustedCustomerContext, Depends(customer_dependency)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> OrderResponse:
    order = await get_owned_order(session, order_id, context.customer_id)
    if order is None:
        raise APIError(404, "resource_not_found", "Resource not found.")
    return OrderResponse(
        id=order.id,
        customer_id=order.customer_id,
        status=order.status,
        total=order.total,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[
            OrderItemResponse(
                order_item_id=item.id,
                product_id=item.product_id,
                sku=item.product.sku,
                product_name=item.product.name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.unit_price * item.quantity,
            )
            for item in order.items
        ],
    )


@router.get(
    "/orders/{order_id}/shipment",
    response_model=ShipmentResponse,
    openapi_extra=customer_openapi_extra(),
)
async def get_shipment(
    order_id: UUID,
    context: Annotated[TrustedCustomerContext, Depends(customer_dependency)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> ShipmentResponse:
    shipment = await get_owned_shipment(session, order_id, context.customer_id)
    if shipment is None:
        order = await get_owned_order(session, order_id, context.customer_id)
        code = "shipment_not_found" if order is not None else "resource_not_found"
        message = "Shipment not found." if code == "shipment_not_found" else "Resource not found."
        raise APIError(404, code, message)
    return ShipmentResponse.model_validate(shipment)


@router.get(
    "/orders/{order_id}/refunds",
    response_model=list[RefundResponse],
    openapi_extra=customer_openapi_extra(),
)
async def get_refunds(
    order_id: UUID,
    context: Annotated[TrustedCustomerContext, Depends(customer_dependency)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> list[RefundResponse]:
    refunds = await get_owned_refunds(session, order_id, context.customer_id)
    if refunds is None:
        raise APIError(404, "resource_not_found", "Resource not found.")
    return [RefundResponse.model_validate(refund) for refund in refunds]
