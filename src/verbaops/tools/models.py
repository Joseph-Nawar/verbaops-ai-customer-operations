"""Strict tool inputs, server-side context, outputs, and registry records."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from verbaops.commerce.models import (
    OrderStatus,
    RefundStatus,
    ShipmentStatus,
)

if TYPE_CHECKING:
    from verbaops.commerce.client import CommerceClient


class ToolModel(BaseModel):
    """Common closed and immutable tool model configuration."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class GetOrderStatusInput(ToolModel):
    """Model-visible input for an order status lookup."""

    order_id: UUID


class GetShipmentStatusInput(ToolModel):
    """Model-visible input for a shipment status lookup."""

    order_id: UUID


class GetRefundStatusInput(ToolModel):
    """Model-visible input for an order refund lookup."""

    order_id: UUID


class SearchProductsInput(ToolModel):
    """Model-visible input for a bounded product search."""

    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    limit: Annotated[int, Field(ge=1, le=10)]


class ListDeliverySlotsInput(ToolModel):
    """Model-visible input for a bounded delivery-slot lookup."""

    date_from: date
    date_to: date
    available_only: bool = True

    @model_validator(mode="after")
    def validate_range(self) -> "ListDeliverySlotsInput":
        span_days = (self.date_to - self.date_from).days
        if span_days < 0:
            raise ValueError("date_to must be on or after date_from")
        if span_days > 31:
            raise ValueError("delivery slot date range must not exceed 31 days")
        return self


class ToolExecutionContext(ToolModel):
    """Trusted server-side context kept separate from model-visible inputs."""

    customer_id: UUID


class GetOrderStatusOutput(ToolModel):
    """Concise order status data suitable for model context."""

    order_id: UUID
    status: OrderStatus
    total: str
    created_at: datetime
    updated_at: datetime


class GetShipmentStatusOutput(ToolModel):
    """Concise shipment status data suitable for model context."""

    order_id: UUID
    shipment_id: UUID
    status: ShipmentStatus
    carrier: str
    tracking_number: str | None
    estimated_delivery: datetime | None
    delivered_at: datetime | None
    delivery_slot_id: UUID | None


class RefundSummary(ToolModel):
    """Concise refund data suitable for model context."""

    refund_id: UUID
    amount: str
    status: RefundStatus
    reason: str
    requires_manual_approval: bool
    created_at: datetime


class GetRefundStatusOutput(ToolModel):
    """Concise order refund data suitable for model context."""

    order_id: UUID
    refunds: tuple[RefundSummary, ...]


class ProductSummary(ToolModel):
    """Concise product data suitable for model context."""

    product_id: UUID
    sku: str
    name: str
    price: str
    stock: int


class SearchProductsOutput(ToolModel):
    """Bounded product search data suitable for model context."""

    items: tuple[ProductSummary, ...]
    limit: int
    offset: int
    has_more: bool


class DeliverySlotSummary(ToolModel):
    """Concise delivery slot data suitable for model context."""

    slot_id: UUID
    service_date: date
    window_start: time
    window_end: time
    capacity: int
    remaining_capacity: int
    available: bool


class ListDeliverySlotsOutput(ToolModel):
    """Bounded delivery-slot data suitable for model context."""

    slots: tuple[DeliverySlotSummary, ...]


class RiskLevel(StrEnum):
    """Tool risk classifications available in M3C."""

    READ_ONLY = "read_only"


@dataclass(frozen=True)
class RetryPolicy:
    """Small explicit retry policy record for read-only tools."""

    max_attempts: int
    retryable_status_codes: tuple[int, ...]
    retry_on_timeout: bool
    retry_on_transport: bool

    @classmethod
    def commerce_read(cls) -> "RetryPolicy":
        """Return the fixed M3C transient-read policy."""

        return cls(
            max_attempts=2,
            retryable_status_codes=(502, 503, 504),
            retry_on_timeout=True,
            retry_on_transport=True,
        )


ToolHandler = Callable[[Any, ToolExecutionContext, "CommerceClient"], Awaitable[BaseModel]]


@dataclass(frozen=True)
class ToolDefinition:
    """Explicit immutable metadata and handler binding for one model tool."""

    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    risk_level: RiskLevel
    timeout_seconds: float
    retry_policy: RetryPolicy
    handler: ToolHandler
