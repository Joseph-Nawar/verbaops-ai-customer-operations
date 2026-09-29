"""Durable grounded-answer execution and deterministic scoring."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, TypeVar

from verbaops.evaluation.m5d_run_identity import (
    bind_checkpoint_identity,
    load_checkpoint_records,
)
from verbaops.evaluation.rag_metrics import citation_precision, grounded_fact_score
from verbaops.evaluation.rag_models import MetricResult, RagCase
from verbaops.evaluation.rag_reports import percentile
from verbaops.evaluation.rag_runner import score_meets_threshold
from verbaops.evaluation.rag_v02 import RagV02Case, recognize_labeled_fact_assertion
from verbaops.retrieval.grounding import SAFE_GROUNDING_FALLBACK

GroundedCase = TypeVar("GroundedCase", RagCase, RagV02Case, contravariant=True)


class GroundedExecutionAdapter(Protocol[GroundedCase]):
    async def execute(self, case: GroundedCase) -> Mapping[str, Any]: ...


_SENSITIVE_KEY_MARKERS = ("api_key", "access_token", "authorization", "credential", "password")
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_SECRET_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


class M5dCaseExecutionError(RuntimeError):
    """Safe case-level interruption details without provider exception payloads."""

    def __init__(self, case_id: str, status_code: int | None, error_type: str) -> None:
        self.case_id = case_id
        self.status_code = status_code
        self.error_type = error_type
        detail = f"M5D evaluation stopped on case {case_id} ({error_type})"
        if status_code is not None:
            detail += f"; HTTP status={status_code}"
        super().__init__(detail)


def _sanitize(value: Any, secrets_to_hide: Sequence[str] = ()) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize(item, secrets_to_hide)
            for key, item in value.items()
            if not any(marker in str(key).casefold() for marker in _SENSITIVE_KEY_MARKERS)
        }
    if isinstance(value, list):
        return [_sanitize(item, secrets_to_hide) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item, secrets_to_hide) for item in value]
    if isinstance(value, str):
        sanitized = _SECRET_PATTERN.sub("[redacted]", _BEARER_PATTERN.sub(r"\1[redacted]", value))
        for secret in secrets_to_hide:
            if secret:
                sanitized = sanitized.replace(secret, "[redacted]")
        return sanitized
    return value


async def run_grounded_evaluation[GroundedCaseType: (RagCase, RagV02Case)](
    cases: Sequence[GroundedCaseType],
    adapter: GroundedExecutionAdapter[GroundedCaseType],
    output_path: Path,
    *,
    secrets_to_hide: Sequence[str] = (),
    delay_seconds_between_cases: float = 0.0,
    record_metadata: Mapping[str, Any] | None = None,
    run_identity: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Execute missing cases and fsync one sanitized JSONL checkpoint per result."""

    if not math.isfinite(delay_seconds_between_cases) or delay_seconds_between_cases < 0:
        raise ValueError("inter-case delay must be a finite non-negative number")
    completed: set[str] = set()
    identity_fingerprint: str | None = None
    if run_identity is not None:
        case_ids = {case.case_id for case in cases}
        identity_fingerprint = bind_checkpoint_identity(output_path, run_identity)
        existing = load_checkpoint_records(output_path, run_identity, expected_case_ids=case_ids)
        completed.update(existing)
    elif output_path.exists():
        for line_number, line in enumerate(output_path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError("record must be an object")
                case_id = str(raw["case_id"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise ValueError(f"invalid grounded checkpoint line {line_number}") from error
            if case_id in completed:
                raise ValueError(f"duplicate grounded checkpoint: {case_id}")
            completed.add(case_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, Any]] = []
    pending_cases = [case for case in cases if case.case_id not in completed]
    for index, case in enumerate(pending_cases):
        try:
            observed = await adapter.execute(case)
        except Exception as error:
            if run_identity is None:
                raise
            response = getattr(error, "response", None)
            status_code = getattr(response, "status_code", None)
            raise M5dCaseExecutionError(
                case.case_id,
                status_code if isinstance(status_code, int) else None,
                type(error).__name__,
            ) from None
        if not isinstance(observed, Mapping):
            raise ValueError("grounded adapter must return a mapping")
        record_data: dict[str, Any] = {
            "case_id": case.case_id,
            **dict(observed),
            **dict(record_metadata or {}),
        }
        record_data["case_id"] = case.case_id
        if run_identity is not None:
            record_data["run_id"] = run_identity["run_id"]
            record_data["run_identity_sha256"] = identity_fingerprint
        if delay_seconds_between_cases > 0:
            record_data["evaluation_inter_case_delay_seconds"] = delay_seconds_between_cases
        record = _sanitize(record_data, secrets_to_hide=secrets_to_hide)
        with output_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        completed.add(case.case_id)
        written.append(record)
        if index < len(pending_cases) - 1 and delay_seconds_between_cases > 0:
            await asyncio.sleep(delay_seconds_between_cases)
    return written


def _judgments(case: RagCase | RagV02Case) -> dict[str, int]:
    return {
        f"{item.document_slug}|{item.document_version}|{item.section}|{item.chunk_index}": item.relevance_grade
        for item in case.relevance_judgments
    }


def _recognized_fact_count(case: RagCase | RagV02Case, answer: str) -> tuple[int, int]:
    normalized = " ".join(answer.casefold().split())
    recognized = 0
    for fact in case.expected_facts:
        if case.dataset_version == "rag-v0.2":
            matched = recognize_labeled_fact_assertion(answer, fact.aliases)
        else:
            matched = bool(fact.aliases) and any(
                alias.casefold() in normalized for alias in fact.aliases
            )
        if matched:
            recognized += 1
    return recognized, len(case.expected_facts)


def score_grounded_records(
    cases: Sequence[RagCase | RagV02Case],
    records: Sequence[Mapping[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    """Score only labeled factual units; no model or LLM judge is involved."""

    by_case = {str(record["case_id"]): record for record in records}
    citation_numerator = 0
    citation_denominator = 0
    grounded_recognized = 0
    grounded_supported = 0
    expected_recognized = 0
    expected_total = 0
    correct_evidence_gate_decisions = 0
    accepted_evidence_turns = 0
    accepted_evidence_with_citations = 0
    safe_fallback_count = 0
    repair_attempts = 0
    repair_successes = 0
    repair_latencies: list[float] = []
    repair_costs: list[float] = []
    latencies: list[float] = []
    cost_observations = 0
    for case in cases:
        record = by_case[case.case_id]
        citations = [str(item) for item in record.get("public_citations", [])]
        case_citations = citation_precision(citations, _judgments(case))
        citation_numerator += case_citations.numerator
        citation_denominator += case_citations.denominator
        answer = str(record.get("final_answer", ""))
        safe_fallback_count += int(answer.strip() == SAFE_GROUNDING_FALLBACK)
        score_options = (
            {"assertion_recognizer": recognize_labeled_fact_assertion}
            if case.dataset_version == "rag-v0.2"
            else {}
        )
        grounded = grounded_fact_score(
            answer,
            [fact.model_dump() for fact in case.expected_facts],
            citations,
            **score_options,
        )
        grounded_recognized += grounded.recognized
        grounded_supported += grounded.supported
        recognized, total = _recognized_fact_count(case, answer)
        expected_recognized += recognized
        expected_total += total
        top_score = record.get("top_confidence_score")
        accepted = (
            score_meets_threshold(float(top_score), threshold) if top_score is not None else False
        )
        correct_evidence_gate_decisions += int(accepted == case.answerable)
        selected_evidence = record.get("selected_evidence", [])
        tool_call_count = record.get("tool_call_count", 0)
        if (
            accepted
            and isinstance(selected_evidence, list)
            and selected_evidence
            and tool_call_count == 0
        ):
            accepted_evidence_turns += 1
            accepted_evidence_with_citations += int(bool(citations))
        attempted_repair = bool(record.get("repair_attempted", False))
        repair_attempts += int(attempted_repair)
        repair_succeeded = attempted_repair and bool(record.get("repair_succeeded", False))
        repair_successes += int(repair_succeeded)
        if attempted_repair:
            repair_latency = record.get("repair_model_latency_ms")
            if isinstance(repair_latency, int | float) and not isinstance(repair_latency, bool):
                repair_latencies.append(float(repair_latency))
            repair_cost = record.get("repair_cost_usd")
            if isinstance(repair_cost, int | float) and not isinstance(repair_cost, bool):
                repair_costs.append(float(repair_cost))
        if record.get("answer_latency_ms") is not None:
            latencies.append(float(record["answer_latency_ms"]))
        cost_observations += int(record.get("cost_usd") is not None)
    grounded_denominator = grounded_recognized
    return {
        "citation_precision": MetricResult(
            numerator=citation_numerator,
            denominator=citation_denominator,
            value=(citation_numerator / citation_denominator if citation_denominator else None),
        ).as_dict(),
        "groundedness": MetricResult(
            numerator=grounded_supported,
            denominator=grounded_denominator,
            value=(grounded_supported / grounded_denominator if grounded_denominator else None),
        ).as_dict(),
        "unsupported_claim_rate": (
            (grounded_recognized - grounded_supported) / grounded_recognized
            if grounded_recognized
            else None
        ),
        "expected_fact_coverage": MetricResult(
            numerator=expected_recognized,
            denominator=expected_total,
            value=(expected_recognized / expected_total if expected_total else None),
        ).as_dict(),
        "retrieval_evidence_gate_accuracy": MetricResult(
            numerator=correct_evidence_gate_decisions,
            denominator=len(cases),
            value=(correct_evidence_gate_decisions / len(cases) if cases else None),
        ).as_dict(),
        "answer_latency_p50_ms": percentile(latencies, 0.5),
        "answer_latency_p95_ms": percentile(latencies, 0.95),
        "cost_metadata_coverage": MetricResult(
            numerator=cost_observations,
            denominator=len(cases),
            value=(cost_observations / len(cases) if cases else None),
        ).as_dict(),
        "accepted_evidence_citation_compliance": MetricResult(
            numerator=accepted_evidence_with_citations,
            denominator=accepted_evidence_turns,
            value=(
                accepted_evidence_with_citations / accepted_evidence_turns
                if accepted_evidence_turns
                else None
            ),
        ).as_dict(),
        "safe_fallback_count": safe_fallback_count,
        "safe_fallback_rate": safe_fallback_count / len(cases) if cases else None,
        "repair_attempts": repair_attempts,
        "repair_successes": repair_successes,
        "repair_failures": repair_attempts - repair_successes,
        "repair_model_latency_p50_ms": percentile(repair_latencies, 0.5),
        "repair_model_latency_p95_ms": percentile(repair_latencies, 0.95),
        "repair_cost_total_usd": sum(repair_costs) if repair_costs else None,
        "repair_cost_mean_usd_over_costed_attempts": (
            sum(repair_costs) / len(repair_costs) if repair_costs else None
        ),
        "repair_cost_observations": len(repair_costs),
        "recognized_fact_units": grounded_recognized,
        "unsupported_fact_units": grounded_recognized - grounded_supported,
    }


__all__ = [
    "GroundedExecutionAdapter",
    "M5dCaseExecutionError",
    "run_grounded_evaluation",
    "score_grounded_records",
]
