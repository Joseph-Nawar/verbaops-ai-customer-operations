"""VerbaOps-owned Pydantic models for the locked Commerce read contract."""

from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class ReturnStatus(StrEnum):
    """Locked NovaCommerce return status values."""

    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    RECEIVED = "received"
    COMPLETED = "completed"


class SupportTicketStatus(StrEnum):
    """Locked NovaCommerce support ticket status values."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class SupportTicketCategory(StrEnum):
    """Locked NovaCommerce support ticket category values."""

    ORDER = "order"
    DELIVERY = "delivery"
    RETURNS_REFUNDS = "returns_refunds"
    PRODUCT = "product"
    WARRANTY = "warranty"
    PAYMENT = "payment"
    ACCOUNT = "account"
    OTHER = "other"


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


class CancelOrderResponse(CommerceModel):
    """Actual NovaCommerce cancellation wrapper, including its optional shipment."""

    order: OrderResponse
    shipment: ShipmentResponse | None


class RescheduleDeliveryRequest(CommerceModel):
    """Fixed reschedule request body."""

    delivery_slot_id: UUID


class ReturnCreateItemRequest(CommerceModel):
    """One order item and quantity in a return request."""

    order_item_id: UUID
    quantity: int = Field(gt=0, le=99)


class ReturnCreateRequest(CommerceModel):
    """Fixed create-return request body."""

    order_id: UUID
    reason: str = Field(min_length=1, max_length=500)
    items: list[ReturnCreateItemRequest] = Field(min_length=1, max_length=50)

    @field_validator("reason")
    @classmethod
    def clean_return_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason must not be blank")
        return cleaned

    @model_validator(mode="after")
    def require_distinct_return_items(self) -> "ReturnCreateRequest":
        identifiers = [item.order_item_id for item in self.items]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("return item identifiers must be distinct")
        return self


class ReturnItemResponse(CommerceModel):
    """One persisted return item."""

    id: UUID
    order_item_id: UUID
    quantity: int


class ReturnResponse(CommerceModel):
    """Created NovaCommerce return request."""

    id: UUID
    order_id: UUID
    reason: str
    status: ReturnStatus
    created_at: datetime
    updated_at: datetime
    items: list[ReturnItemResponse]


class SupportTicketCreateRequest(CommerceModel):
    """Fixed support-ticket creation request body."""

    order_id: UUID | None = None
    category: SupportTicketCategory
    subject: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=5000)

    @field_validator("subject", "description")
    @classmethod
    def clean_ticket_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text must not be blank")
        return cleaned


class SupportTicketResponse(CommerceModel):
    """Created NovaCommerce support ticket."""

    id: UUID
    customer_id: UUID
    order_id: UUID | None
    category: SupportTicketCategory
    subject: str
    description: str
    status: SupportTicketStatus
    created_at: datetime
    updated_at: datetime


class RefundApprovalReference(CommerceModel):
    """Durable supervisor evidence accepted by the high-value refund route."""

    action_request_id: UUID
    proposal_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class RefundCreateRequest(CommerceModel):
    """Fixed refund request body with optional durable supervisor evidence."""

    amount: Decimal = Field(gt=Decimal("0.00"))
    reason: str = Field(min_length=1, max_length=500)
    approval_reference: RefundApprovalReference | None = None

    @field_validator("amount")
    @classmethod
    def require_cent_precision(cls, value: Decimal) -> Decimal:
        normalized = value.quantize(Decimal("0.01"))
        if normalized != value:
            raise ValueError("refund amount must use at most two decimal places")
        return normalized

    @field_validator("reason")
    @classmethod
    def clean_refund_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason must not be blank")
        return cleaned


class WriteRefundResponse(CommerceModel):
    """Created refund request; this does not mean payment settlement completed."""

    id: UUID
    amount: Decimal
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


class TenantCurrencyResponse(CommerceModel):
    """Canonical trusted currency configured by the Commerce tenant."""

    currency_code: str

    @field_validator("currency_code")
    @classmethod
    def require_uppercase_currency_code(cls, value: str) -> str:
        if len(value) != 3 or not value.isascii() or not value.isalpha() or value != value.upper():
            raise ValueError("currency code must be three uppercase letters")
        return value
