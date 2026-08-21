"""Refund response schema."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from novacommerce.db.models.refund import RefundStatus
from novacommerce.schemas.common import ResponseModel


class RefundResponse(ResponseModel):
    id: UUID
    amount: Decimal
    status: RefundStatus
    reason: str
    requires_manual_approval: bool
    created_at: datetime
