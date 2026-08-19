"""Liveness, readiness, and version routes."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from relayai import __version__
from relayai.api.dependencies import get_settings
from relayai.config.settings import Settings

router = APIRouter(tags=["operations"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready"]
    checks: list[str]


class VersionResponse(BaseModel):
    service: str
    version: str
    environment: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
async def ready() -> ReadyResponse:
    return ReadyResponse(status="ready", checks=[])


@router.get("/version", response_model=VersionResponse)
async def version(
    settings: Annotated[Settings, Depends(get_settings)],
) -> VersionResponse:
    return VersionResponse(
        service="relayai",
        version=__version__,
        environment=settings.environment.value,
    )
