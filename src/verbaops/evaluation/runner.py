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
from verbaops.evaluation.metrics import aggregate_results, score_case
from verbaops.evaluation.models import (
    EvaluationCase,
    EvaluationObservation,
    EvaluationRunMetadata,
    EvaluationSummary,
    ObservedToolCall,
)
from verbaops.evaluation.reports import write_artifacts
from verbaops.evaluation.repository import EvaluationRepository


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
            response = "Please provide your " + " and ".join(field.replace("_", " ") for field in outcome.clarification_fields) + "."
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
            "tool_schema_version": metadata.tool_schema_version if metadata else TOOL_SCHEMA_VERSION,
            "capability_alias": first.capability_alias if first and first.capability_alias else (metadata.capability_alias if metadata else summary.capability_alias),
            "gateway_model_id": first.gateway_model_id if first else (metadata.gateway_model_id if metadata else None),
            "model": first.model if first else (metadata.model if metadata else None),
            "provider": first.provider if first else (metadata.provider if metadata else None),
        }
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
    results = []
    if repository is not None and session is None:
        raise ValueError("evaluation repository mode requires an async session")
    if repository is not None and session is not None:
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
        observation = await adapter.observe(case)
        observations.append(observation)
        results.append(score_case(case, observation))
    observation_tuple = tuple(observations)
    result_tuple = tuple(results)
    summary = _summary_metadata(
        aggregate_results(result_tuple, observation_tuple),
        actual_run_id,
        dataset_sha256,
        metadata,
        observation_tuple,
    )
    if repository is not None and session is not None:
        for result in result_tuple:
            await repository.add_result(session, actual_run_id, result)
        await repository.complete_run(session, actual_run_id, summary, datetime.now(UTC))
        await session.commit()
    write_artifacts(actual_run_id, summary, result_tuple, output_root)
    return summary
