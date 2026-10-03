"""Stage 6 customer-scoped read handlers using authenticated identity."""

from uuid import UUID

from verbaops.commerce.client import CommerceClient
from verbaops.commerce.errors import CommerceNotFoundError
from verbaops.tools.models import (
    DeliverySlotSummary,
    GetOrderStatusInput,
    GetOrderStatusOutput,
    GetRefundStatusInput,
    GetRefundStatusOutput,
    GetShipmentStatusInput,
    GetShipmentStatusOutput,
    ListDeliverySlotsInput,
    ListDeliverySlotsOutput,
    ProductSummary,
    RefundSummary,
    SearchProductsInput,
    SearchProductsOutput,
)
from verbaops.tools.stage6_models import (
    MissingTrustedCustomerContextError,
    Stage6ToolExecutionContext,
)


def _require_commerce_tenant(
    context: Stage6ToolExecutionContext,
    client: CommerceClient,
) -> None:
    if context.trusted_context.tenant_id != client.tenant_id:
        raise CommerceNotFoundError()


def _trusted_customer_id(
    context: Stage6ToolExecutionContext,
    client: CommerceClient,
) -> UUID:
    _require_commerce_tenant(context, client)
    customer_id = context.trusted_context.customer_id
    if customer_id is None:
        raise MissingTrustedCustomerContextError()
    return customer_id


async def get_order_status(
    input_data: GetOrderStatusInput,
    context: Stage6ToolExecutionContext,
    client: CommerceClient,
) -> GetOrderStatusOutput:
    """Return concise order status for the authenticated customer's order."""

    order = await client.get_order(input_data.order_id, _trusted_customer_id(context, client))
    return GetOrderStatusOutput(
        order_id=order.id,
        status=order.status,
        total=order.total,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


async def get_shipment_status(
    input_data: GetShipmentStatusInput,
    context: Stage6ToolExecutionContext,
    client: CommerceClient,
) -> GetShipmentStatusOutput:
    """Return concise shipment status for the authenticated customer's order."""

    shipment = await client.get_shipment(input_data.order_id, _trusted_customer_id(context, client))
    return GetShipmentStatusOutput(
        order_id=shipment.order_id,
        shipment_id=shipment.id,
        status=shipment.status,
        carrier=shipment.carrier,
        tracking_number=shipment.tracking_number,
        estimated_delivery=shipment.estimated_delivery,
        delivered_at=shipment.delivered_at,
        delivery_slot_id=shipment.delivery_slot_id,
    )


async def get_refund_status(
    input_data: GetRefundStatusInput,
    context: Stage6ToolExecutionContext,
    client: CommerceClient,
) -> GetRefundStatusOutput:
    """Return concise refund status for the authenticated customer's order."""

    refunds = await client.get_refunds(input_data.order_id, _trusted_customer_id(context, client))
    return GetRefundStatusOutput(
        order_id=input_data.order_id,
        refunds=tuple(
            RefundSummary(
                refund_id=refund.id,
                amount=refund.amount,
                status=refund.status,
                reason=refund.reason,
                requires_manual_approval=refund.requires_manual_approval,
                created_at=refund.created_at,
            )
            for refund in refunds
        ),
    )


async def search_products(
    input_data: SearchProductsInput,
    context: Stage6ToolExecutionContext,
    client: CommerceClient,
) -> SearchProductsOutput:
    """Search the catalog only through the bound Commerce tenant."""

    _require_commerce_tenant(context, client)
    response = await client.search_products(input_data.query, input_data.limit)
    return SearchProductsOutput(
        items=tuple(
            ProductSummary(
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                price=product.price,
                stock=product.stock,
            )
            for product in response.items
        ),
        limit=response.limit,
        offset=response.offset,
        has_more=response.has_more,
    )


async def list_delivery_slots(
    input_data: ListDeliverySlotsInput,
    context: Stage6ToolExecutionContext,
    client: CommerceClient,
) -> ListDeliverySlotsOutput:
    """List delivery slots only through the bound Commerce tenant."""

    _require_commerce_tenant(context, client)
    slots = await client.list_delivery_slots(
        input_data.date_from,
        input_data.date_to,
        input_data.available_only,
    )
    return ListDeliverySlotsOutput(
        slots=tuple(
            DeliverySlotSummary(
                slot_id=slot.id,
                service_date=slot.service_date,
                window_start=slot.window_start,
                window_end=slot.window_end,
                capacity=slot.capacity,
                remaining_capacity=slot.remaining_capacity,
                available=slot.available,
            )
            for slot in slots
        )
    )


__all__ = [
    "get_order_status",
    "get_refund_status",
    "get_shipment_status",
    "list_delivery_slots",
    "search_products",
]
