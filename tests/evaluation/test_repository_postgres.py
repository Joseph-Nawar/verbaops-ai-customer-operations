"""Real PostgreSQL persistence contracts for evaluation runs and results."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from verbaops.evaluation.models import (
    CaseEvaluationResult,
    EvaluationRunMetadata,
    ExpectedOutcome,
    MetricValue,
)
from verbaops.evaluation.repository import EvaluationRepository

pytestmark = pytest.mark.evaluation_postgres


@pytest.fixture(scope="module")
def database_url() -> str:
    url = os.environ.get("VERBAOPS_DATABASE__URL") or os.environ.get(
        "NOVACOMMERCE_TEST_DATABASE_URL"
    )
    if not url:
        pytest.skip("evaluation PostgreSQL tests require VERBAOPS_DATABASE__URL")
    return url


@pytest_asyncio.fixture(scope="module")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    database_engine = create_async_engine(database_url, pool_pre_ping=True, echo=False)
    yield database_engine
    await database_engine.dispose()


@pytest_asyncio.fixture
async def clean_eval_tables(engine: AsyncEngine) -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE TABLE eval_results, eval_runs RESTART IDENTITY CASCADE")
        )
    yield


def metadata() -> EvaluationRunMetadata:
    return EvaluationRunMetadata(
        id=uuid4(),
        dataset_version="text-agent-v0.1",
        dataset_sha256="a" * 64,
        git_sha="b" * 40,
        environment="test",
        capability_alias="deterministic-fixture",
        gateway_model_id=None,
        model=None,
        provider=None,
        prompt_version="text-agent-system-v1",
        graph_version="text-agent-v1",
        tool_schema_version="commerce-read-tools-v1",
        case_count=1,
        started_at=datetime.now(UTC),
    )


def result(case_id: str = "repo-case-001") -> CaseEvaluationResult:
    metric = MetricValue(status="available", numerator=1, denominator=1)
    return CaseEvaluationResult(
        case_id=case_id,
        split="dev",
        category="order-status",
        language="en",
        passed=True,
        expected_tool="get_order_status",
        observed_tools=("get_order_status",),
        expected_arguments={"order_id": "54d93c0f-951e-5d74-afdd-80d33d4c8c95"},
        observed_arguments={"order_id": "54d93c0f-951e-5d74-afdd-80d33d4c8c95"},
        expected_outcome=ExpectedOutcome(
            kind="grounded_tool_answer", authoritative_facts={"status": "processing"}
        ),
        observed_outcome={"status": "processing", "nested": {"ok": True}},
        metric_details={"tool_selection": metric},
        latency_ms=4.5,
        cost_usd=None,
    )


@pytest.mark.asyncio
async def test_run_lifecycle_jsonb_round_trip_and_summary_update(
    engine: AsyncEngine, clean_eval_tables: None
) -> None:
    repository = EvaluationRepository()
    run = metadata()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await repository.create_run(session, run)
        await repository.add_result(session, run.id, result())
        await repository.complete_run(
            session, run.id, {"overall_case_pass_rate": {"numerator": 1}}, datetime.now(UTC)
        )
        await session.commit()
        loaded = await repository.get_run(session, run.id)
        results = await repository.list_results(session, run.id)
    assert loaded.status == "completed"
    assert loaded.summary == {"overall_case_pass_rate": {"numerator": 1}}
    assert results[0].observed_outcome["nested"] == {"ok": True}


@pytest.mark.asyncio
async def test_unique_run_case_and_foreign_key_constraints(
    engine: AsyncEngine, clean_eval_tables: None
) -> None:
    repository = EvaluationRepository()
    run = metadata()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await repository.create_run(session, run)
        await repository.add_result(session, run.id, result())
        with pytest.raises(IntegrityError):
            await repository.add_result(session, run.id, result())
        await session.rollback()
        with pytest.raises(IntegrityError):
            await repository.add_result(session, uuid4(), result("orphan"))
        await session.rollback()


@pytest.mark.asyncio
async def test_same_case_id_is_isolated_between_runs(
    engine: AsyncEngine, clean_eval_tables: None
) -> None:
    repository = EvaluationRepository()
    first, second = metadata(), metadata()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await repository.create_run(session, first)
        await repository.create_run(session, second)
        await repository.add_result(session, first.id, result("shared-case"))
        await repository.add_result(session, second.id, result("shared-case"))
        await session.commit()
        first_results = await repository.list_results(session, first.id)
        second_results = await repository.list_results(session, second.id)
    assert [item.case_id for item in first_results] == ["shared-case"]
    assert [item.case_id for item in second_results] == ["shared-case"]


@pytest.mark.asyncio
async def test_nonnegative_run_constraints_are_enforced(
    engine: AsyncEngine, clean_eval_tables: None
) -> None:
    run = metadata()
    async with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            await connection.execute(
                text(
                    "INSERT INTO eval_runs (id, dataset_version, dataset_sha256, git_sha, environment, "
                    "capability_alias, prompt_version, graph_version, tool_schema_version, status, case_count, started_at) "
                    "VALUES (:id, 'text-agent-v0.1', :sha, :git, 'test', 'fixture', 'prompt', 'graph', 'tools', 'running', -1, now())"
                ),
                {"id": run.id, "sha": "a" * 64, "git": "b" * 40},
            )
