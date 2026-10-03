"""The five explicit, read-only NovaCommerce tool handlers."""

from verbaops.commerce.client import CommerceClient
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
    ToolExecutionContext,
)


async def get_order_status(
    input_data: GetOrderStatusInput,
    context: ToolExecutionContext,
    client: CommerceClient,
) -> GetOrderStatusOutput:
    """Return the trusted customer's concise order status."""

    order = await client.get_order(input_data.order_id, context.customer_id)
    return GetOrderStatusOutput(
        order_id=order.id,
        status=order.status,
        total=order.total,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


async def get_shipment_status(
    input_data: GetShipmentStatusInput,
    context: ToolExecutionContext,
    client: CommerceClient,
) -> GetShipmentStatusOutput:
    """Return the trusted customer's concise shipment status."""

    shipment = await client.get_shipment(input_data.order_id, context.customer_id)
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
    context: ToolExecutionContext,
    client: CommerceClient,
) -> GetRefundStatusOutput:
    """Return the trusted customer's concise refund status."""

    refunds = await client.get_refunds(input_data.order_id, context.customer_id)
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
    _context: ToolExecutionContext,
    client: CommerceClient,
) -> SearchProductsOutput:
    """Return bounded product search results without customer identity."""

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
    _context: ToolExecutionContext,
    client: CommerceClient,
) -> ListDeliverySlotsOutput:
    """Return bounded delivery-slot results without customer identity."""

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
