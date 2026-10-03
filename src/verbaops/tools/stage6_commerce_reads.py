"""Stage 6 customer-scoped read handlers using authenticated identity."""

from uuid import UUID

from verbaops.commerce.client import CommerceClient
from verbaops.tools.models import (
    GetOrderStatusInput,
    GetOrderStatusOutput,
    GetRefundStatusInput,
    GetRefundStatusOutput,
    GetShipmentStatusInput,
    GetShipmentStatusOutput,
    RefundSummary,
)
from verbaops.tools.stage6_models import (
    MissingTrustedCustomerContextError,
    Stage6ToolExecutionContext,
)


def _trusted_customer_id(context: Stage6ToolExecutionContext) -> UUID:
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

    order = await client.get_order(input_data.order_id, _trusted_customer_id(context))
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

    shipment = await client.get_shipment(input_data.order_id, _trusted_customer_id(context))
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

    refunds = await client.get_refunds(input_data.order_id, _trusted_customer_id(context))
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


__all__ = ["get_order_status", "get_refund_status", "get_shipment_status"]
