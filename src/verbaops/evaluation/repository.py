"""Focused persistence boundary for evaluation runs and case results."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from verbaops.evaluation.models import (
    CaseEvaluationResult,
    EvaluationRunMetadata,
    EvaluationSummary,
    ExpectedOutcome,
    MetricValue,
)
from verbaops.evaluation.repository_tables import eval_results, eval_runs


class EvaluationRepositoryError(RuntimeError):
    """Raised when an evaluation persistence operation cannot complete."""


def _summary_dict(summary: EvaluationSummary | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    if isinstance(summary, EvaluationSummary):
        return summary.model_dump(mode="json")
    return dict(summary)


class EvaluationRepository:
    """Async SQLAlchemy Core repository isolated from runtime repositories."""

    async def create_run(self, session: AsyncSession, metadata: EvaluationRunMetadata) -> UUID:
        """Insert one run without committing the caller-owned transaction."""

        await session.execute(
            insert(eval_runs).values(
                id=metadata.id,
                dataset_version=metadata.dataset_version,
                dataset_sha256=metadata.dataset_sha256,
                git_sha=metadata.git_sha,
                environment=metadata.environment,
                capability_alias=metadata.capability_alias,
                gateway_model_id=metadata.gateway_model_id,
                model=metadata.model,
                provider=metadata.provider,
                prompt_version=metadata.prompt_version,
                graph_version=metadata.graph_version,
                tool_schema_version=metadata.tool_schema_version,
                started_at=metadata.started_at,
                completed_at=metadata.completed_at,
                status=metadata.status,
                case_count=metadata.case_count,
                summary_json=metadata.summary,
                latency_ms=metadata.latency_ms,
                cost_usd=metadata.cost_usd,
            )
        )
        return metadata.id

    async def add_result(
        self,
        session: AsyncSession,
        eval_run_id: UUID,
        result: CaseEvaluationResult,
    ) -> UUID:
        """Insert one scored result without committing the caller transaction."""

        result_id = uuid4()
        await session.execute(
            insert(eval_results).values(
                id=result_id,
                eval_run_id=eval_run_id,
                case_id=result.case_id,
                split=result.split,
                category=result.category,
                language=result.language,
                passed=result.passed,
                expected_tool=result.expected_tool,
                observed_tools=list(result.observed_tools),
                expected_arguments=result.expected_arguments,
                observed_arguments=result.observed_arguments,
                expected_outcome=result.expected_outcome.model_dump(mode="json"),
                observed_outcome=result.observed_outcome,
                metric_details={
                    name: metric.model_dump(mode="json")
                    for name, metric in result.metric_details.items()
                },
                failure_reasons=list(result.failure_reasons),
                latency_ms=result.latency_ms,
                cost_usd=result.cost_usd,
                agent_run_id=result.agent_run_id,
            )
        )
        return result_id

    async def complete_run(
        self,
        session: AsyncSession,
        eval_run_id: UUID,
        summary: EvaluationSummary | Mapping[str, Any],
        completed_at: datetime,
    ) -> None:
        """Mark a run completed and store its aggregate JSONB summary."""

        summary_json = _summary_dict(summary)
        latency_ms = summary.latency_p95_ms if isinstance(summary, EvaluationSummary) else None
        cost_usd = summary.total_cost_usd if isinstance(summary, EvaluationSummary) else None
        existing_id = await session.scalar(
            select(eval_runs.c.id).where(eval_runs.c.id == eval_run_id)
        )
        if existing_id is None:
            raise EvaluationRepositoryError("evaluation run does not exist")
        await session.execute(
            update(eval_runs)
            .where(eval_runs.c.id == eval_run_id)
            .values(
                status="completed",
                completed_at=completed_at,
                summary_json=summary_json,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
            )
        )

    async def get_run(self, session: AsyncSession, eval_run_id: UUID) -> EvaluationRunMetadata:
        """Read one run into its application-owned metadata model."""

        row = (
            (await session.execute(select(eval_runs).where(eval_runs.c.id == eval_run_id)))
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise EvaluationRepositoryError("evaluation run does not exist")
        return EvaluationRunMetadata(
            id=row["id"],
            dataset_version=row["dataset_version"],
            dataset_sha256=row["dataset_sha256"],
            git_sha=row["git_sha"],
            environment=row["environment"],
            capability_alias=row["capability_alias"],
            gateway_model_id=row["gateway_model_id"],
            model=row["model"],
            provider=row["provider"],
            prompt_version=row["prompt_version"],
            graph_version=row["graph_version"],
            tool_schema_version=row["tool_schema_version"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            status=row["status"],
            case_count=row["case_count"],
            summary=row["summary_json"],
            latency_ms=row["latency_ms"],
            cost_usd=row["cost_usd"],
        )

    async def list_results(
        self,
        session: AsyncSession,
        eval_run_id: UUID,
    ) -> tuple[CaseEvaluationResult, ...]:
        """Read one run's results in insertion-independent case order."""

        rows = (
            await session.execute(
                select(eval_results)
                .where(eval_results.c.eval_run_id == eval_run_id)
                .order_by(eval_results.c.case_id)
            )
        ).mappings()
        return tuple(
            CaseEvaluationResult(
                case_id=row["case_id"],
                split=row["split"],
                category=row["category"],
                language=row["language"],
                passed=row["passed"],
                expected_tool=row["expected_tool"],
                observed_tools=tuple(row["observed_tools"]),
                expected_arguments=row["expected_arguments"],
                observed_arguments=row["observed_arguments"],
                expected_outcome=ExpectedOutcome.model_validate(row["expected_outcome"]),
                observed_outcome=row["observed_outcome"],
                metric_details={
                    name: MetricValue.model_validate(value)
                    for name, value in row["metric_details"].items()
                },
                failure_reasons=tuple(row["failure_reasons"]),
                latency_ms=row["latency_ms"],
                cost_usd=row["cost_usd"],
                agent_run_id=row["agent_run_id"],
            )
            for row in rows
        )
