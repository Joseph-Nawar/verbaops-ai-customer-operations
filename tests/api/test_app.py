"""Application factory and dependency-container tests."""

from pathlib import Path

import pytest
from fastapi import FastAPI

from verbaops.agent.evaluation import AgentEvaluationProfile, GroundingCandidate
from verbaops.api.app import create_app

from .conftest import build_provider, build_settings, request


def test_application_factory_returns_independent_instances() -> None:
    first_settings = build_settings()
    second_settings = build_settings()
    first_provider = build_provider()
    second_provider = build_provider()

    first = create_app(settings=first_settings, auth_provider=first_provider)
    second = create_app(settings=second_settings, auth_provider=second_provider)

    assert isinstance(first, FastAPI)
    assert isinstance(second, FastAPI)
    assert first is not second
    assert first.state.verbaops_dependencies is not second.state.verbaops_dependencies
    assert first.state.verbaops_dependencies.settings is first_settings
    assert second.state.verbaops_dependencies.settings is second_settings
    assert first.state.verbaops_dependencies.auth_provider is first_provider
    assert second.state.verbaops_dependencies.auth_provider is second_provider


def test_p4_trace_sink_requires_explicit_candidate_and_canonical_run_identity(
    tmp_path: Path,
) -> None:
    settings = build_settings()
    provider = build_provider()
    profile = AgentEvaluationProfile(
        grounding_candidate=GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS
    )

    with pytest.raises(ValueError, match="P4 trace"):
        create_app(settings=settings, auth_provider=provider, evaluation_profile=profile)

    run_id = "canonical-p4-app"
    run_directory = tmp_path / run_id
    app = create_app(
        settings=settings,
        auth_provider=provider,
        evaluation_profile=profile,
        p4_trace_run_directory=run_directory,
        p4_trace_run_id=run_id,
    )

    assert app.state.verbaops_dependencies.p4_trace_run_directory == run_directory
    assert app.state.verbaops_dependencies.p4_trace_run_id == run_id


def test_non_p4_application_rejects_evaluation_trace_sink(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="P4 trace"):
        create_app(
            settings=build_settings(),
            auth_provider=build_provider(),
            p4_trace_run_directory=tmp_path / "run",
            p4_trace_run_id="run",
        )


@pytest.mark.asyncio
async def test_application_metadata_uses_package_version(app: FastAPI) -> None:
    response = await request(app, "GET", "/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "VerbaOps AI"
    assert response.json()["info"]["version"] == "0.1.0"
