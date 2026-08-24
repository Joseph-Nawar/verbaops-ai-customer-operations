"""VerbaOps-owned Pydantic models for the locked Commerce read contract."""

from datetime import date, datetime, time
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CommerceModel(BaseModel):
    """Common immutable, closed response model configuration."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class OrderStatus(StrEnum):
    """Locked Commerce order status values."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class ShipmentStatus(StrEnum):
    """Locked Commerce shipment status values."""

    PENDING = "pending"
    LABEL_CREATED = "label_created"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    CANCELLED = "cancelled"


class RefundStatus(StrEnum):
    """Locked Commerce refund status values."""

    APPROVED = "approved"
    PENDING_MANUAL_APPROVAL = "pending_manual_approval"
    REJECTED = "rejected"
    COMPLETED = "completed"


class OrderItemResponse(CommerceModel):
    """An item in a Commerce order response."""

    order_item_id: UUID
    product_id: UUID
    sku: str
    product_name: str
    quantity: int
    unit_price: str
    line_total: str


class OrderResponse(CommerceModel):
    """A Commerce order response."""

    id: UUID
    customer_id: UUID
    status: OrderStatus
    total: str
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]


class ShipmentResponse(CommerceModel):
    """A Commerce shipment response."""

    id: UUID
    order_id: UUID
    carrier: str
    tracking_number: str | None
    status: ShipmentStatus
    estimated_delivery: datetime | None
    delivered_at: datetime | None
    delivery_slot_id: UUID | None


class RefundResponse(CommerceModel):
    """A Commerce refund response."""

    id: UUID
    amount: str
    status: RefundStatus
    reason: str
    requires_manual_approval: bool
    created_at: datetime


class ProductResponse(CommerceModel):
    """A product in a Commerce search response."""

    id: UUID
    sku: str
    name: str
    description: str
    price: str
    stock: int


class ProductSearchResponse(CommerceModel):
    """A paginated Commerce product search response."""

    items: list[ProductResponse]
    limit: int
    offset: int
    has_more: bool


class DeliverySlotResponse(CommerceModel):
    """A Commerce delivery slot response."""

    id: UUID
    service_date: date
    window_start: time
    window_end: time
    capacity: int
    reserved_count: int
    remaining_capacity: int
    available: bool
