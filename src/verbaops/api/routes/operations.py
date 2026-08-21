"""Liveness, dependency readiness, and version routes."""

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from verbaops import __version__
from verbaops.api.dependencies import get_settings
from verbaops.cache.redis import ping_redis
from verbaops.config.settings import Settings
from verbaops.db.resources import ping_database

router = APIRouter(tags=["operations"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: list["ReadyCheck"]


class ReadyCheck(BaseModel):
    name: Literal["postgres", "redis"]
    status: Literal["ok", "unavailable"]


class VersionResponse(BaseModel):
    service: str
    version: str
    environment: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
async def ready(request: Request) -> JSONResponse:
    """Check configured runtime dependencies without exposing connection details."""

    resources = getattr(request.app.state, "verbaops_runtime_resources", None)
    database = getattr(resources, "database", None)
    redis = getattr(resources, "redis", None)

    async def check_database() -> bool:
        if database is None:
            return False
        try:
            return await ping_database(database)
        except Exception:
            return False

    async def check_redis() -> bool:
        if redis is None:
            return False
        try:
            return await ping_redis(redis)
        except Exception:
            return False

    postgres_ok, redis_ok = await asyncio.gather(check_database(), check_redis())
    checks = [
        ReadyCheck(name="postgres", status="ok" if postgres_ok else "unavailable"),
        ReadyCheck(name="redis", status="ok" if redis_ok else "unavailable"),
    ]
    status: Literal["ready", "not_ready"] = "ready" if postgres_ok and redis_ok else "not_ready"
    response = ReadyResponse(status=status, checks=checks)
    return JSONResponse(
        status_code=200 if status == "ready" else 503,
        content=response.model_dump(),
    )


@router.get("/version", response_model=VersionResponse)
async def version(
    settings: Annotated[Settings, Depends(get_settings)],
) -> VersionResponse:
    return VersionResponse(
        service="verbaops",
        version=__version__,
        environment=settings.environment.value,
    )
