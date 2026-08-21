"""Customer response schema."""

from datetime import datetime
from uuid import UUID

from novacommerce.schemas.common import ResponseModel


class CustomerResponse(ResponseModel):
    id: UUID
    name: str
    email: str
    language: str
    created_at: datetime
