"""Product and paginated-search response schemas."""

from decimal import Decimal
from uuid import UUID

from novacommerce.schemas.common import ResponseModel


class ProductResponse(ResponseModel):
    id: UUID
    sku: str
    name: str
    description: str
    price: Decimal
    stock: int


class ProductSearchResponse(ResponseModel):
    items: list[ProductResponse]
    limit: int
    offset: int
    has_more: bool
