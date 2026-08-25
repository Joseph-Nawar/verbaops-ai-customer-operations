"""Pluggable deterministic evaluation runner for M4A and future M4B adapters."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from verbaops.agent.versions import GRAPH_VERSION, PROMPT_VERSION, TOOL_SCHEMA_VERSION
from verbaops.evaluation.corpus import CorpusManifest, audit_corpus
from verbaops.evaluation.errors import (
    ProviderExecutionError,
    ProviderQuotaExceeded,
    interruption_summary,
)
from verbaops.evaluation.metrics import aggregate_results, score_case
from verbaops.evaluation.models import (
    CaseEvaluationResult,
    EvaluationCase,
    EvaluationObservation,
    EvaluationRunMetadata,
    EvaluationSummary,
    ObservedToolCall,
    SafetyOutcome,
)
from verbaops.evaluation.reports import write_artifacts
from verbaops.evaluation.repository import EvaluationRepository, EvaluationRepositoryError


class EvaluationAdapter(Protocol):
    """Interface for one case execution source."""

    async def observe(self, case: EvaluationCase) -> EvaluationObservation:
        """Execute one case and return application-owned observations."""


class DeterministicFixtureAdapter:
    """Provider-free adapter that materializes observations from case labels."""

    async def observe(self, case: EvaluationCase) -> EvaluationObservation:
        outcome = case.expected_outcome
        observed_tools: tuple[ObservedToolCall, ...] = ()
        authoritative_results: tuple[dict[str, Any], ...] = ()
        answer_facts: dict[str, Any] = {}
        if case.expected_tool is not None:
            facts = {**outcome.authoritative_facts}
            if outcome.kind == "safe_not_found":
                facts = {"not_found": True}
            result = facts or {"ok": True}
            observed_tools = (
                ObservedToolCall(
                    tool_name=case.expected_tool,
                    arguments=case.expected_arguments,
                    result=result,
                ),
            )
            authoritative_results = (result,)
            answer_facts = facts
        if outcome.kind == "clarify":
            response = (
                "Please provide your "
                + " and ".join(field.replace("_", " ") for field in outcome.clarification_fields)
                + "."
            )
        elif outcome.kind == "refuse":
            response = "I cannot perform that request."
        elif outcome.kind == "benign_response":
            response = "I can help with read-only order, shipment, refund, product, and delivery questions."
        elif outcome.kind == "safe_not_found":
            response = "I could not find an authorized record for that request."
        else:
            answer_facts = {**outcome.authoritative_facts}
            response = " ".join(str(value) for value in outcome.authoritative_facts.values())
        return EvaluationObservation(
            observed_tools=observed_tools,
            final_response=response,
            authoritative_tool_results=authoritative_results,
            answer_facts=answer_facts,
            capability_alias="deterministic-fixture",
            latency_ms=1.0,
            cost_usd=None,
            started_at=datetime.now(UTC),
        )


def _summary_metadata(
    summary: EvaluationSummary,
    run_id: UUID,
    dataset_sha256: str,
    metadata: EvaluationRunMetadata | None,
    observations: tuple[EvaluationObservation, ...],
) -> EvaluationSummary:
    first = next((item for item in observations if item.capability_alias is not None), None)
    return summary.model_copy(
        update={
            "run_id": run_id,
            "dataset_sha256": dataset_sha256,
            "dataset_version": metadata.dataset_version if metadata else summary.dataset_version,
            "prompt_version": metadata.prompt_version if metadata else PROMPT_VERSION,
            "graph_version": metadata.graph_version if metadata else GRAPH_VERSION,
            "tool_schema_version": metadata.tool_schema_version
            if metadata
            else TOOL_SCHEMA_VERSION,
            "capability_alias": first.capability_alias
            if first and first.capability_alias
            else (metadata.capability_alias if metadata else summary.capability_alias),
            "gateway_model_id": first.gateway_model_id
            if first
            else (metadata.gateway_model_id if metadata else None),
            "model": first.model if first else (metadata.model if metadata else None),
            "provider": first.provider if first else (metadata.provider if metadata else None),
        }
    )


def _observation_from_result(
    result: Any,
    metadata: EvaluationRunMetadata,
) -> EvaluationObservation:
    """Reconstruct only aggregateable evidence for a previously persisted case."""

    observed_outcome = result.observed_outcome
    safety = observed_outcome.get("safety", {}) if isinstance(observed_outcome, dict) else {}
    answer_facts = (
        observed_outcome.get("answer_facts", {}) if isinstance(observed_outcome, dict) else {}
    )
    return EvaluationObservation(
        answer_facts=answer_facts if isinstance(answer_facts, dict) else {},
        safety=SafetyOutcome.model_validate(safety if isinstance(safety, dict) else {}),
        capability_alias=metadata.capability_alias,
        gateway_model_id=metadata.gateway_model_id,
        model=metadata.model,
        provider=metadata.provider,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        agent_run_id=result.agent_run_id,
    )


async def run_evaluation(
    cases: tuple[EvaluationCase, ...],
    adapter: EvaluationAdapter,
    *,
    manifest: CorpusManifest,
    scenario_manifest: Mapping[str, Any],
    dataset_bytes: bytes,
    output_root: Path = Path("artifacts/eval_runs"),
    run_id: UUID | None = None,
    metadata: EvaluationRunMetadata | None = None,
    repository: EvaluationRepository | None = None,
    session: AsyncSession | None = None,
) -> EvaluationSummary:
    """Audit, execute, score, optionally persist, aggregate, and artifact a run."""

    audit_corpus(manifest, cases, scenario_manifest)
    actual_run_id = run_id or (metadata.id if metadata else uuid4())
    dataset_sha256 = hashlib.sha256(dataset_bytes).hexdigest()
    observations: list[EvaluationObservation] = []
    results: list[CaseEvaluationResult] = []
    if repository is not None and session is None:
        raise ValueError("evaluation repository mode requires an async session")
    run_metadata: EvaluationRunMetadata | None = metadata
    persisted_case_ids: set[str] = set()
    if repository is not None and session is not None:
        try:
            existing_run = await repository.get_run(session, actual_run_id)
        except EvaluationRepositoryError:
            existing_run = None
        if existing_run is not None:
            run_metadata = existing_run
            existing_results = await repository.list_results(session, actual_run_id)
            results.extend(existing_results)
            persisted_case_ids = {result.case_id for result in existing_results}
            observations.extend(
                _observation_from_result(result, existing_run) for result in existing_results
            )
        else:
            run_metadata = metadata or EvaluationRunMetadata(
                id=actual_run_id,
                dataset_version=manifest.dataset_version,
                dataset_sha256=dataset_sha256,
                git_sha="local",
                environment="local",
                capability_alias="deterministic-fixture",
                prompt_version=PROMPT_VERSION,
                graph_version=GRAPH_VERSION,
                tool_schema_version=TOOL_SCHEMA_VERSION,
                case_count=len(cases),
                started_at=datetime.now(UTC),
            )
            await repository.create_run(session, run_metadata)
    for case in cases:
        if case.case_id in persisted_case_ids:
            continue
        try:
            observation = await adapter.observe(case)
        except ProviderQuotaExceeded as error:
            if repository is not None and session is not None and run_metadata is not None:
                error.run_id = actual_run_id
                error.completed_case_count = len(results)
                error.remaining_case_count = len(cases) - len(results)
                await repository.interrupt_run(
                    session,
                    actual_run_id,
                    interruption_summary(
                        reason=error.reason,
                        completed_case_count=error.completed_case_count,
                        remaining_case_count=error.remaining_case_count,
                        retry_after_seconds=error.retry_after_seconds,
                        reset_metadata=error.reset_metadata,
                    ),
                    datetime.now(UTC),
                )
                await session.commit()
            raise
        except ProviderExecutionError:
            if repository is not None and session is not None:
                await repository.interrupt_run(
                    session,
                    actual_run_id,
                    interruption_summary(
                        reason="provider_failure",
                        completed_case_count=len(results),
                        remaining_case_count=len(cases) - len(results),
                    ),
                    datetime.now(UTC),
                )
                await session.commit()
            raise
        observations.append(observation)
        result = score_case(case, observation)
        results.append(result)
        persisted_case_ids.add(case.case_id)
        if repository is not None and session is not None and run_metadata is not None:
            await repository.add_result(session, actual_run_id, result)
            progress = _summary_metadata(
                aggregate_results(tuple(results), tuple(observations)),
                actual_run_id,
                dataset_sha256,
                run_metadata,
                tuple(observations),
            )
            run_metadata = run_metadata.model_copy(
                update={
                    "gateway_model_id": progress.gateway_model_id,
                    "model": progress.model,
                    "provider": progress.provider,
                }
            )
            await repository.update_progress(session, actual_run_id, progress, run_metadata)
            await session.commit()
    observation_tuple = tuple(observations)
    result_tuple = tuple(results)
    summary = _summary_metadata(
        aggregate_results(result_tuple, observation_tuple),
        actual_run_id,
        dataset_sha256,
        run_metadata,
        observation_tuple,
    )
    if repository is not None and session is not None:
        await repository.complete_run(session, actual_run_id, summary, datetime.now(UTC))
        await session.commit()
    write_artifacts(actual_run_id, summary, result_tuple, output_root)
    return summary
