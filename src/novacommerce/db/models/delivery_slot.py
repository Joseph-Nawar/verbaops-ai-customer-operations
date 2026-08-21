"""Delivery-slot model."""

from datetime import date, time
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, Integer, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novacommerce.db.base import Base
from novacommerce.db.models.common import uuid_column


class DeliverySlot(Base):
    __tablename__ = "delivery_slots"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="capacity_positive"),
        CheckConstraint("reserved_count >= 0", name="reserved_non_negative"),
        CheckConstraint("reserved_count <= capacity", name="reserved_within_capacity"),
        CheckConstraint("window_end > window_start", name="window_order"),
        UniqueConstraint(
            "service_date", "window_start", "window_end", name="uq_delivery_slots_window"
        ),
    )

    id: Mapped[UUID] = uuid_column()
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_start: Mapped[time] = mapped_column(Time(timezone=True), nullable=False)
    window_end: Mapped[time] = mapped_column(Time(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    shipments = relationship("Shipment", back_populates="delivery_slot")
