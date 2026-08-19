"""Immutable server-derived identity context."""

from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Role(StrEnum):
    """Roles that may be assigned by the trusted authentication provider."""

    CUSTOMER = "customer"
    SUPPORT_AGENT = "support_agent"
    SUPPORT_SUPERVISOR = "support_supervisor"
    TENANT_ADMIN = "tenant_admin"


class TrustedContext(BaseModel):
    """Validated identity facts supplied to downstream application boundaries."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    principal_id: UUID
    tenant_id: UUID
    customer_id: UUID | None
    roles: frozenset[Role]
