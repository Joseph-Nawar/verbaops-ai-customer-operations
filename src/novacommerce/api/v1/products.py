"""Authenticated active-product search endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.api.dependencies import get_database_session
from novacommerce.api.errors import APIError
from novacommerce.api.v1.dependencies import service_dependency
from novacommerce.schemas.products import ProductResponse, ProductSearchResponse
from novacommerce.services.products import search_products

router = APIRouter(tags=["products"])


@router.get("/products/search", response_model=ProductSearchResponse)
async def search(
    _: Annotated[str, Depends(service_dependency)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> ProductSearchResponse:
    query = q.strip()
    if not query or len(query) > 100:
        raise APIError(422, "invalid_query", "Request validation failed.")
    products, has_more = await search_products(session, query, limit, offset)
    return ProductSearchResponse(
        items=[ProductResponse.model_validate(product) for product in products],
        limit=limit,
        offset=offset,
        has_more=has_more,
    )
