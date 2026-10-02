"""VerbaOps AI FastAPI application factory."""

from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from verbaops import __version__
from verbaops.agent.evaluation import AgentEvaluationProfile, GroundingCandidate
from verbaops.api.dependencies import ApplicationDependencies, RuntimeResourceUnavailableError
from verbaops.api.errors import (
    PublicAPIError,
    authentication_error_handler,
    http_exception_handler,
    public_api_error_handler,
    runtime_resource_error_handler,
    validation_error_handler,
)
from verbaops.api.lifespan import lifespan
from verbaops.api.middleware import RequestContextMiddleware
from verbaops.api.routes.conversations import router as conversations_router
from verbaops.api.routes.knowledge_admin import router as knowledge_admin_router
from verbaops.api.routes.operations import router as operations_router
from verbaops.auth.provider import AuthenticationError, AuthProvider
from verbaops.config.settings import Settings
from verbaops.observability.logging import configure_logging


def create_app(
    *,
    settings: Settings,
    auth_provider: AuthProvider,
    evaluation_profile: AgentEvaluationProfile | None = None,
    p4_trace_run_directory: Path | None = None,
    p4_trace_run_id: str | None = None,
    p5_trace_run_directory: Path | None = None,
    p5_trace_run_id: str | None = None,
) -> FastAPI:
    """Create an independent VerbaOps AI FastAPI application instance."""

    is_p4 = bool(
        evaluation_profile is not None
        and evaluation_profile.grounding_candidate
        is GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS
    )
    if is_p4 != (p4_trace_run_directory is not None and p4_trace_run_id is not None):
        raise ValueError("P4 trace run directory and canonical run ID are required only for P4")
    if (p4_trace_run_directory is None) != (p4_trace_run_id is None):
        raise ValueError("P4 trace directory and run ID must be configured together")
    if (
        p4_trace_run_id is not None
        and p4_trace_run_directory is not None
        and (not p4_trace_run_id or p4_trace_run_directory.name != p4_trace_run_id)
    ):
        raise ValueError("P4 trace path must match its canonical run ID")
    is_p5 = bool(
        evaluation_profile is not None
        and evaluation_profile.grounding_candidate
        is GroundingCandidate.P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS
    )
    if is_p5 != (p5_trace_run_directory is not None and p5_trace_run_id is not None):
        raise ValueError("P5 trace run directory and canonical run ID are required only for P5")
    if (p5_trace_run_directory is None) != (p5_trace_run_id is None):
        raise ValueError("P5 trace directory and run ID must be configured together")
    if (
        p5_trace_run_id is not None
        and p5_trace_run_directory is not None
        and (not p5_trace_run_id or p5_trace_run_directory.name != p5_trace_run_id)
    ):
        raise ValueError("P5 trace path must match its canonical run ID")

    configure_logging(settings)
    app = FastAPI(
        title="VerbaOps AI",
        version=__version__,
        description="VerbaOps AI multilingual customer-operations application foundation.",
        lifespan=lifespan,
    )
    app.state.verbaops_dependencies = ApplicationDependencies(
        settings=settings,
        auth_provider=auth_provider,
        evaluation_profile=evaluation_profile,
        p4_trace_run_directory=p4_trace_run_directory,
        p4_trace_run_id=p4_trace_run_id,
        p5_trace_run_directory=p5_trace_run_directory,
        p5_trace_run_id=p5_trace_run_id,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(AuthenticationError, cast(Any, authentication_error_handler))
    app.add_exception_handler(
        RuntimeResourceUnavailableError,
        cast(Any, runtime_resource_error_handler),
    )
    app.add_exception_handler(PublicAPIError, cast(Any, public_api_error_handler))
    app.add_exception_handler(RequestValidationError, cast(Any, validation_error_handler))
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.include_router(operations_router)
    app.include_router(conversations_router)
    app.include_router(knowledge_admin_router)
    return app
