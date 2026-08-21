"""Shipment response schema."""

from datetime import datetime
from uuid import UUID

from novacommerce.db.models.shipment import ShipmentStatus
from novacommerce.schemas.common import ResponseModel


class ShipmentResponse(ResponseModel):
    id: UUID
    order_id: UUID
    carrier: str
    tracking_number: str | None
    status: ShipmentStatus
    estimated_delivery: datetime | None
    delivered_at: datetime | None
    delivery_slot_id: UUID | None
