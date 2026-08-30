"""Durable grounded-answer execution and deterministic scoring."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from verbaops.evaluation.rag_metrics import citation_precision, grounded_fact_score
from verbaops.evaluation.rag_models import MetricResult, RagCase
from verbaops.evaluation.rag_reports import percentile
from verbaops.evaluation.rag_runner import score_meets_threshold


class GroundedExecutionAdapter(Protocol):
    async def execute(self, case: RagCase) -> Mapping[str, Any]: ...


_SENSITIVE_KEY_MARKERS = ("api_key", "access_token", "authorization", "credential", "password")
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_SECRET_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if not any(marker in str(key).casefold() for marker in _SENSITIVE_KEY_MARKERS)
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _SECRET_PATTERN.sub("[redacted]", _BEARER_PATTERN.sub(r"\1[redacted]", value))
    return value


async def run_grounded_evaluation(
    cases: Sequence[RagCase], adapter: GroundedExecutionAdapter, output_path: Path
) -> list[dict[str, Any]]:
    """Execute missing cases and fsync one sanitized JSONL checkpoint per result."""

    completed: set[str] = set()
    if output_path.exists():
        for line_number, line in enumerate(output_path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                raw = json.loads(line)
                case_id = str(raw["case_id"])
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                raise ValueError(f"invalid grounded checkpoint line {line_number}") from error
            if case_id in completed:
                raise ValueError(f"duplicate grounded checkpoint: {case_id}")
            completed.add(case_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, Any]] = []
    for case in cases:
        if case.case_id in completed:
            continue
        observed = await adapter.execute(case)
        if not isinstance(observed, Mapping):
            raise ValueError("grounded adapter must return a mapping")
        record = _sanitize({"case_id": case.case_id, **dict(observed)})
        with output_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        completed.add(case.case_id)
        written.append(record)
    return written


def _judgments(case: RagCase) -> dict[str, int]:
    return {
        f"{item.document_slug}|{item.document_version}|{item.section}|{item.chunk_index}": item.relevance_grade
        for item in case.relevance_judgments
    }


def _recognized_fact_count(case: RagCase, answer: str) -> tuple[int, int]:
    normalized = " ".join(answer.casefold().split())
    recognized = 0
    for fact in case.expected_facts:
        if fact.aliases and any(alias.casefold() in normalized for alias in fact.aliases):
            recognized += 1
    return recognized, len(case.expected_facts)


def score_grounded_records(
    cases: Sequence[RagCase], records: Sequence[Mapping[str, Any]], threshold: float
) -> dict[str, Any]:
    """Score only labeled factual units; no model or LLM judge is involved."""

    by_case = {str(record["case_id"]): record for record in records}
    citation_numerator = 0
    citation_denominator = 0
    grounded_recognized = 0
    grounded_supported = 0
    expected_recognized = 0
    expected_total = 0
    correct_abstentions = 0
    latencies: list[float] = []
    cost_observations = 0
    for case in cases:
        record = by_case[case.case_id]
        citations = [str(item) for item in record.get("public_citations", [])]
        case_citations = citation_precision(citations, _judgments(case))
        citation_numerator += case_citations.numerator
        citation_denominator += case_citations.denominator
        answer = str(record.get("final_answer", ""))
        grounded = grounded_fact_score(
            answer, [fact.model_dump() for fact in case.expected_facts], citations
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
        correct_abstentions += int(accepted == case.answerable)
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
        "abstention_accuracy": MetricResult(
            numerator=correct_abstentions,
            denominator=len(cases),
            value=(correct_abstentions / len(cases) if cases else None),
        ).as_dict(),
        "answer_latency_p50_ms": percentile(latencies, 0.5),
        "answer_latency_p95_ms": percentile(latencies, 0.95),
        "cost_metadata_coverage": MetricResult(
            numerator=cost_observations,
            denominator=len(cases),
            value=(cost_observations / len(cases) if cases else None),
        ).as_dict(),
        "recognized_fact_units": grounded_recognized,
        "unsupported_fact_units": grounded_recognized - grounded_supported,
    }


__all__ = ["GroundedExecutionAdapter", "run_grounded_evaluation", "score_grounded_records"]
