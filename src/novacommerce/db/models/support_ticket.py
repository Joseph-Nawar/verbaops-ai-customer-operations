"""Support-ticket model and status values."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novacommerce.db.base import Base
from novacommerce.db.models.common import enum_column, timestamp_column, uuid_column


class SupportTicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class SupportTicketCategory(StrEnum):
    ORDER = "order"
    DELIVERY = "delivery"
    RETURNS_REFUNDS = "returns_refunds"
    PRODUCT = "product"
    WARRANTY = "warranty"
    PAYMENT = "payment"
    ACCOUNT = "account"
    OTHER = "other"


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[UUID] = uuid_column()
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), nullable=False)
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    category: Mapped[SupportTicketCategory] = mapped_column(
        SQLAlchemyEnum(
            SupportTicketCategory,
            name="support_tickets_category",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=SupportTicketCategory.OTHER,
        server_default=SupportTicketCategory.OTHER.value,
    )
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[SupportTicketStatus] = enum_column(
        SupportTicketStatus, name="support_tickets_status"
    )
    created_at: Mapped[datetime] = timestamp_column()
    updated_at: Mapped[datetime] = timestamp_column(onupdate=True)

    customer = relationship("Customer", back_populates="support_tickets")
    order = relationship("Order", back_populates="support_tickets")
