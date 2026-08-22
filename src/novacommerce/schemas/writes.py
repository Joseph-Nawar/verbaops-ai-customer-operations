"""M2D write request and response schemas."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from novacommerce.db.models.refund import RefundStatus
from novacommerce.db.models.return_ import ReturnStatus
from novacommerce.db.models.support_ticket import SupportTicketStatus
from novacommerce.schemas.common import ResponseModel
from novacommerce.schemas.orders import OrderResponse
from novacommerce.schemas.shipments import ShipmentResponse


class WriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrderCreateItemRequest(WriteRequest):
    product_id: UUID
    quantity: int = Field(ge=1, le=99)


class OrderCreateRequest(WriteRequest):
    items: list[OrderCreateItemRequest] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def product_ids_are_distinct(self) -> "OrderCreateRequest":
        ids = [item.product_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("product IDs must be distinct")
        return self


class RescheduleRequest(WriteRequest):
    delivery_slot_id: UUID


class ReturnCreateItemRequest(WriteRequest):
    order_item_id: UUID
    quantity: int = Field(gt=0, le=99)


class ReturnCreateRequest(WriteRequest):
    order_id: UUID
    reason: str = Field(max_length=500)
    items: list[ReturnCreateItemRequest] = Field(min_length=1, max_length=50)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason must not be blank")
        return cleaned

    @model_validator(mode="after")
    def order_item_ids_are_distinct(self) -> "ReturnCreateRequest":
        ids = [item.order_item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("order item IDs must be distinct")
        return self


class RefundCreateRequest(WriteRequest):
    amount: Decimal = Field(gt=Decimal("0.00"))
    reason: str = Field(max_length=500)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason must not be blank")
        return cleaned


class SupportTicketCreateRequest(WriteRequest):
    order_id: UUID | None = None
    subject: str = Field(max_length=300)
    description: str = Field(max_length=5000)

    @field_validator("subject", "description")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text must not be blank")
        return cleaned


class CreateOrderResponse(ResponseModel):
    order: OrderResponse
    shipment: ShipmentResponse


class CancelOrderResponse(ResponseModel):
    order: OrderResponse
    shipment: ShipmentResponse | None


class ReturnItemResponse(ResponseModel):
    id: UUID
    order_item_id: UUID
    quantity: int


class ReturnResponse(ResponseModel):
    id: UUID
    order_id: UUID
    reason: str
    status: ReturnStatus
    created_at: datetime
    updated_at: datetime
    items: list[ReturnItemResponse]


class SupportTicketResponse(ResponseModel):
    id: UUID
    customer_id: UUID
    order_id: UUID | None
    subject: str
    description: str
    status: SupportTicketStatus
    created_at: datetime
    updated_at: datetime


class WriteRefundResponse(ResponseModel):
    id: UUID
    amount: Decimal
    status: RefundStatus
    reason: str
    requires_manual_approval: bool
    created_at: datetime
