"""Shipment model and status values."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novacommerce.db.base import Base
from novacommerce.db.models.common import enum_column, uuid_column


class ShipmentStatus(StrEnum):
    PENDING = "pending"
    LABEL_CREATED = "label_created"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    CANCELLED = "cancelled"


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_shipments_order_id"),
        UniqueConstraint("tracking_number", name="uq_shipments_tracking_number"),
    )

    id: Mapped[UUID] = uuid_column()
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    carrier: Mapped[str] = mapped_column(String(100), nullable=False)
    tracking_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[ShipmentStatus] = enum_column(ShipmentStatus, name="shipments_status")
    estimated_delivery: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_slot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("delivery_slots.id"), nullable=True
    )

    order = relationship("Order", back_populates="shipment")
    delivery_slot = relationship("DeliverySlot", back_populates="shipments")
