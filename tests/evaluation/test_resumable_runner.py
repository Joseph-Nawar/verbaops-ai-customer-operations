"""Provider-free contracts for one resumable genuine evaluation run."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from verbaops.evaluation.cases import load_cases
from verbaops.evaluation.corpus import load_manifest
from verbaops.evaluation.errors import ProviderExecutionError, ProviderQuotaExceeded
from verbaops.evaluation.models import (
    CaseEvaluationResult,
    EvaluationObservation,
    EvaluationRunMetadata,
    EvaluationSummary,
)
from verbaops.evaluation.repository import EvaluationRepositoryError
from verbaops.evaluation.runner import DeterministicFixtureAdapter, run_evaluation

ROOT = Path(__file__).parents[2]


class MemoryEvaluationRepository:
    """Small real-behavior repository double with transaction-like methods."""

    def __init__(self) -> None:
        self.runs: dict[UUID, EvaluationRunMetadata] = {}
        self.results: dict[UUID, dict[str, CaseEvaluationResult]] = {}

    async def create_run(self, _session: object, metadata: EvaluationRunMetadata) -> UUID:
        self.runs[metadata.id] = metadata
        self.results[metadata.id] = {}
        return metadata.id

    async def get_run(self, _session: object, run_id: UUID) -> EvaluationRunMetadata:
        try:
            return self.runs[run_id]
        except KeyError:
            raise EvaluationRepositoryError("evaluation run does not exist") from None

    async def list_results(
        self, _session: object, run_id: UUID
    ) -> tuple[CaseEvaluationResult, ...]:
        return tuple(self.results[run_id].values())

    async def add_result(
        self, _session: object, run_id: UUID, result: CaseEvaluationResult
    ) -> UUID:
        if result.case_id in self.results[run_id]:
            raise AssertionError("duplicate case result")
        self.results[run_id][result.case_id] = result
        return result.agent_run_id or UUID("00000000-0000-0000-0000-000000000001")

    async def update_progress(
        self,
        _session: object,
        run_id: UUID,
        summary: EvaluationSummary,
        metadata: EvaluationRunMetadata,
    ) -> None:
        self.runs[run_id] = metadata.model_copy(
            update={
                "summary": summary.model_dump(mode="json"),
                "gateway_model_id": summary.gateway_model_id,
                "model": summary.model,
                "provider": summary.provider,
                "latency_ms": summary.latency_p95_ms,
                "cost_usd": summary.total_cost_usd,
            }
        )

    async def interrupt_run(
        self,
        _session: object,
        run_id: UUID,
        summary: dict[str, Any],
        _completed_at: datetime,
    ) -> None:
        self.runs[run_id] = self.runs[run_id].model_copy(
            update={"status": "failed", "summary": summary, "completed_at": _completed_at}
        )

    async def complete_run(
        self,
        _session: object,
        run_id: UUID,
        summary: EvaluationSummary,
        completed_at: datetime,
    ) -> None:
        self.runs[run_id] = self.runs[run_id].model_copy(
            update={
                "status": "completed",
                "summary": summary.model_dump(mode="json"),
                "completed_at": completed_at,
                "gateway_model_id": summary.gateway_model_id,
                "model": summary.model,
                "provider": summary.provider,
            }
        )


class MemorySession:
    async def commit(self) -> None:
        return None


def _fixture_inputs() -> tuple[tuple[Any, ...], Any, dict[str, Any]]:
    cases = load_cases(ROOT / "evals/agent/v0.1/cases.jsonl")[:3]
    manifest = load_manifest(ROOT / "evals/agent/v0.1/manifest.json").model_copy(
        update={
            "expected_case_count": 3,
            "split_counts": {"dev": 3, "release_holdout": 0},
            "category_counts": {
                "order-status": 3,
                "shipment-status": 0,
                "refund-status": 0,
                "product-search": 0,
                "delivery-slots": 0,
                "missing-ambiguous-identifiers": 0,
                "unsupported-write": 0,
                "safety-injection-identity-cross-customer": 0,
                "benign-no-tool": 0,
            },
        }
    )
    scenario_manifest = json.loads(
        (ROOT / "tests/acceptance/fixtures/novacommerce-scenarios.json").read_text()
    )
    return cases, manifest, scenario_manifest


def _metadata(run_id: UUID, case_count: int) -> EvaluationRunMetadata:
    return EvaluationRunMetadata(
        id=run_id,
        dataset_version="text-agent-v0.1",
        dataset_sha256="a" * 64,
        git_sha="b" * 40,
        environment="test",
        capability_alias="agent-fast",
        prompt_version="text-agent-system-v1",
        graph_version="text-agent-v1",
        tool_schema_version="commerce-read-tools-v1",
        case_count=case_count,
        started_at=datetime.now(UTC),
    )


class QuotaAfterOne:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fixture = DeterministicFixtureAdapter()

    async def observe(self, case: Any) -> EvaluationObservation:
        self.calls.append(case.case_id)
        if len(self.calls) == 2:
            raise ProviderQuotaExceeded(retry_after_seconds=42)
        observation = await self.fixture.observe(case)
        return observation.model_copy(
            update={
                "capability_alias": "agent-fast",
                "model": "groq/openai/gpt-oss-120b",
                "provider": "Groq",
            }
        )


@pytest.mark.asyncio
async def test_quota_interruption_persists_completed_cases_and_resume_skips_them(
    tmp_path: Path,
) -> None:
    cases, manifest, scenario_manifest = _fixture_inputs()
    repository = MemoryEvaluationRepository()
    run_id = UUID("11111111-1111-1111-1111-111111111111")
    adapter = QuotaAfterOne()
    with pytest.raises(ProviderQuotaExceeded) as interruption:
        await run_evaluation(
            cases,
            adapter,
            manifest=manifest,
            scenario_manifest=scenario_manifest,
            dataset_bytes=(ROOT / "evals/agent/v0.1/cases.jsonl").read_bytes(),
            output_root=tmp_path,
            run_id=run_id,
            metadata=_metadata(run_id, len(cases)),
            repository=repository,
            session=MemorySession(),
        )

    assert interruption.value.run_id == run_id
    assert interruption.value.completed_case_count == 1
    assert [case.case_id for case in cases[:1]] == list(repository.results[run_id])
    assert repository.runs[run_id].status == "failed"

    class ResumeAdapter:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.fixture = DeterministicFixtureAdapter()

        async def observe(self, case: Any) -> EvaluationObservation:
            self.calls.append(case.case_id)
            observation = await self.fixture.observe(case)
            return observation.model_copy(
                update={
                    "capability_alias": "agent-fast",
                    "model": "groq/openai/gpt-oss-120b",
                    "provider": "Groq",
                }
            )

    resumed = ResumeAdapter()
    summary = await run_evaluation(
        cases,
        resumed,
        manifest=manifest,
        scenario_manifest=scenario_manifest,
        dataset_bytes=(ROOT / "evals/agent/v0.1/cases.jsonl").read_bytes(),
        output_root=tmp_path,
        run_id=run_id,
        metadata=_metadata(run_id, len(cases)),
        repository=repository,
        session=MemorySession(),
    )

    assert summary.run_id == run_id
    assert resumed.calls == [case.case_id for case in cases[1:]]
    assert repository.runs[run_id].status == "completed"
    assert len(repository.results[run_id]) == 3
    assert len(set(repository.results[run_id])) == 3


@pytest.mark.asyncio
async def test_ordinary_provider_failure_is_not_persisted_as_a_successful_observation(
    tmp_path: Path,
) -> None:
    cases, manifest, scenario_manifest = _fixture_inputs()
    repository = MemoryEvaluationRepository()
    run_id = UUID("22222222-2222-2222-2222-222222222222")

    class FailedAdapter:
        async def observe(self, _case: Any) -> EvaluationObservation:
            raise ProviderExecutionError("provider unavailable")

    with pytest.raises(ProviderExecutionError):
        await run_evaluation(
            cases,
            FailedAdapter(),
            manifest=manifest,
            scenario_manifest=scenario_manifest,
            dataset_bytes=(ROOT / "evals/agent/v0.1/cases.jsonl").read_bytes(),
            output_root=tmp_path,
            run_id=run_id,
            metadata=_metadata(run_id, len(cases)),
            repository=repository,
            session=MemorySession(),
        )

    assert repository.results[run_id] == {}
    assert repository.runs[run_id].status == "failed"
    assert repository.runs[run_id].summary == {
        "status": "interrupted",
        "reason": "provider_failure",
        "completed_case_count": 0,
        "remaining_case_count": 3,
    }
