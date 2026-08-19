"""Common declarative base for future RelayAI-owned models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Metadata registry intentionally containing no M1D application tables."""
