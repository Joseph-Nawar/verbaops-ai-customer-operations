"""Delivery-slot response schema with derived availability."""

from datetime import date, time
from uuid import UUID

from pydantic import computed_field

from novacommerce.schemas.common import ResponseModel


class DeliverySlotResponse(ResponseModel):
    id: UUID
    service_date: date
    window_start: time
    window_end: time
    capacity: int
    reserved_count: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def remaining_capacity(self) -> int:
        return self.capacity - self.reserved_count

    @computed_field  # type: ignore[prop-decorator]
    @property
    def available(self) -> bool:
        return self.remaining_capacity > 0
