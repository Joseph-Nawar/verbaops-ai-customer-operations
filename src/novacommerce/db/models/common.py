"""Shared SQLAlchemy 2 model building blocks."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Numeric
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for ORM defaults."""

    return datetime.now(UTC)


def uuid_column() -> Mapped[UUID]:
    """Return the standard UUID primary-key column definition."""

    return mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)


def timestamp_column(*, nullable: bool = False, onupdate: bool = False) -> Mapped[datetime]:
    """Return a timezone-aware timestamp column definition."""

    return mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now if onupdate else None,
        nullable=nullable,
    )


def money_column(*, nullable: bool = False) -> Mapped[Any]:
    """Return a Decimal-backed fixed precision money column."""

    return mapped_column(Numeric(12, 2, asdecimal=True), nullable=nullable)


def enum_column[T: Enum](enum_type: type[T], *, name: str) -> Mapped[T]:
    """Return a constrained, non-native SQL enum column."""

    return mapped_column(
        SQLAlchemyEnum(
            enum_type,
            name=name,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
    )
