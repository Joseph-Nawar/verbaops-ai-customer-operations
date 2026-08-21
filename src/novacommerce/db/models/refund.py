"""Refund model and status values."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novacommerce.db.base import Base
from novacommerce.db.models.common import enum_column, money_column, timestamp_column, uuid_column


class RefundStatus(StrEnum):
    APPROVED = "approved"
    PENDING_MANUAL_APPROVAL = "pending_manual_approval"
    REJECTED = "rejected"
    COMPLETED = "completed"


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)

    id: Mapped[UUID] = uuid_column()
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    amount: Mapped[Decimal] = money_column()
    status: Mapped[RefundStatus] = enum_column(RefundStatus, name="refunds_status")
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    requires_manual_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = timestamp_column()

    order = relationship("Order", back_populates="refunds")
