"""Return and return-item models with status values."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novacommerce.db.base import Base
from novacommerce.db.models.common import enum_column, timestamp_column, uuid_column


class ReturnStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    RECEIVED = "received"
    COMPLETED = "completed"


class Return(Base):
    __tablename__ = "returns"

    id: Mapped[UUID] = uuid_column()
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[ReturnStatus] = enum_column(ReturnStatus, name="returns_status")
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = timestamp_column(onupdate=True)

    order = relationship("Order", back_populates="returns")
    items = relationship("ReturnItem", back_populates="return_record", cascade="all, delete-orphan")


class ReturnItem(Base):
    __tablename__ = "return_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        UniqueConstraint("return_id", "order_item_id", name="uq_return_items_return_order_item"),
    )

    id: Mapped[UUID] = uuid_column()
    return_id: Mapped[UUID] = mapped_column(ForeignKey("returns.id"), nullable=False)
    order_item_id: Mapped[UUID] = mapped_column(ForeignKey("order_items.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    return_record = relationship("Return", back_populates="items")
    order_item = relationship("OrderItem", back_populates="return_items")
