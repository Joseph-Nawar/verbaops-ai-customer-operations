"""Authenticated delivery-slot listing endpoint."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.api.dependencies import get_database_session
from novacommerce.api.errors import APIError
from novacommerce.api.v1.dependencies import service_dependency
from novacommerce.clock import SystemUTCClock
from novacommerce.schemas.delivery_slots import DeliverySlotResponse
from novacommerce.services.delivery_slots import list_delivery_slots

router = APIRouter(tags=["delivery-slots"])
FROM_DATE_QUERY = Query(None)
TO_DATE_QUERY = Query(None)
AVAILABLE_ONLY_QUERY = Query(True)


@router.get("/delivery-slots", response_model=list[DeliverySlotResponse])
async def list_slots(
    request: Request,
    _: Annotated[str, Depends(service_dependency)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
    from_date: date | None = FROM_DATE_QUERY,
    to_date: date | None = TO_DATE_QUERY,
    available_only: bool = AVAILABLE_ONLY_QUERY,
) -> list[DeliverySlotResponse]:
    clock = getattr(request.app.state, "novacommerce_clock", SystemUTCClock())
    try:
        slots = await list_delivery_slots(
            session,
            clock,
            from_date=from_date,
            to_date=to_date,
            available_only=available_only,
        )
    except ValueError as error:
        raise APIError(422, "invalid_query", "Request validation failed.") from error
    return [DeliverySlotResponse.model_validate(slot) for slot in slots]
