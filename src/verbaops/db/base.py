"""Common declarative base for VerbaOps AI-owned models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Metadata registry for VerbaOps-owned persistence models."""
