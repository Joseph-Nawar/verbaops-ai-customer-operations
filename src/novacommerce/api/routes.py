"""Operational-only NovaCommerce routes."""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from novacommerce import __version__
from novacommerce.db.resources import ping_database

router = APIRouter(tags=["operations"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyCheck(BaseModel):
    name: Literal["postgres"]
    status: Literal["ok", "unavailable"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: list[ReadyCheck]


class VersionResponse(BaseModel):
    service: str
    version: str
    environment: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
async def ready(request: Request) -> JSONResponse:
    """Check only PostgreSQL and never expose connection details."""

    resources = getattr(request.app.state, "novacommerce_runtime_resources", None)
    database = getattr(resources, "database", None)
    healthy = False
    if database is not None:
        try:
            healthy = await ping_database(database)
        except Exception:
            healthy = False
    status: Literal["ready", "not_ready"] = "ready" if healthy else "not_ready"
    response = ReadyResponse(
        status=status,
        checks=[ReadyCheck(name="postgres", status="ok" if healthy else "unavailable")],
    )
    return JSONResponse(status_code=200 if healthy else 503, content=response.model_dump())


@router.get("/version", response_model=VersionResponse)
async def version(request: Request) -> VersionResponse:
    settings = request.app.state.novacommerce_settings
    return VersionResponse(
        service="novacommerce",
        version=__version__,
        environment=settings.environment.value,
    )
