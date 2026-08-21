"""Order and nested order-item response schemas."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from novacommerce.db.models.order import OrderStatus
from novacommerce.schemas.common import ResponseModel


class OrderItemResponse(ResponseModel):
    order_item_id: UUID
    product_id: UUID
    sku: str
    product_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class OrderResponse(ResponseModel):
    id: UUID
    customer_id: UUID
    status: OrderStatus
    total: Decimal
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]
