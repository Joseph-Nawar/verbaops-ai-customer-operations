"""Order model and status values."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novacommerce.db.base import Base
from novacommerce.db.models.common import enum_column, money_column, timestamp_column, uuid_column


class OrderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[UUID] = uuid_column()
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    status: Mapped[OrderStatus] = enum_column(OrderStatus, name="orders_status")
    total: Mapped[Decimal] = money_column()
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = timestamp_column(onupdate=True)
    cancelled_at: Mapped[datetime | None] = timestamp_column(nullable=True)

    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    shipment = relationship("Shipment", back_populates="order", uselist=False)
    refunds = relationship("Refund", back_populates="order")
    returns = relationship("Return", back_populates="order")
    support_tickets = relationship("SupportTicket", back_populates="order")
