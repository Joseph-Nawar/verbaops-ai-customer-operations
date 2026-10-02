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
from verbaops.evaluation.p4_trace import frozen_p4_observability_contract
from verbaops.evaluation.p5_trace import (
    P5_KNOWLEDGE_TERMINAL_OUTPUT_TRANSPORT,
    P5_TRACE_FIELDS,
)
from verbaops.evaluation.rag_metrics import citation_precision, grounded_fact_score
from verbaops.evaluation.rag_models import MetricResult, RagCase
from verbaops.evaluation.rag_reports import percentile
from verbaops.evaluation.rag_runner import score_meets_threshold
from verbaops.evaluation.rag_v02 import RagV02Case, recognize_labeled_fact_assertion
from verbaops.evaluation.rag_v02_scorer_impl import classify_labeled_fact_assertion
from verbaops.evaluation.rag_v02_scorer_v2 import audit_scorer_v2
from verbaops.retrieval.grounding import SAFE_GROUNDING_FALLBACK

GroundedCase = TypeVar("GroundedCase", RagCase, RagV02Case, contravariant=True)


class GroundedExecutionAdapter(Protocol[GroundedCase]):
    async def execute(self, case: GroundedCase) -> Mapping[str, Any]: ...


_SENSITIVE_KEY_MARKERS = ("api_key", "access_token", "authorization", "credential", "password")
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_SECRET_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_P4_CLAIM_DIAGNOSTIC_FIELDS = {"claim_text", "evidence_handle", "supporting_excerpt"}


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


def score_p4_grounded_records(
    cases: Sequence[RagV02Case],
    records: Sequence[Mapping[str, Any]],
    threshold: float,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Score a complete P4 record set with one frozen scorer-v2 assessment per fact."""

    if len(cases) != 96 or len(records) != 96 or any(case.split != "dev" for case in cases):
        raise ValueError("P4 scoring requires all 96 complete DEV cases")
    if any(case.dataset_version != "rag-v0.2" for case in cases):
        raise ValueError("P4 scorer-v2 accepts only rag-v0.2 cases")
    case_ids = [case.case_id for case in cases]
    record_ids = [str(record.get("case_id", "")) for record in records]
    if len(set(case_ids)) != len(case_ids) or len(set(record_ids)) != len(record_ids):
        raise ValueError("P4 case IDs and checkpoint records must be unique")
    if set(case_ids) != set(record_ids):
        raise ValueError("P4 cannot score an incomplete or unexpected record set")

    audit = audit_scorer_v2(repo_root)
    fixture_rows = audit["fixtures"].get("facts")
    if not isinstance(fixture_rows, list):
        raise ValueError("audited scorer-v2 fixtures have no fact list")
    fixture_by_key: dict[str, Mapping[str, Any]] = {}
    for row in fixture_rows:
        if not isinstance(row, Mapping):
            raise ValueError("audited scorer-v2 fact fixture is malformed")
        key = f"{row.get('case_id')}::{row.get('fact_id')}"
        if key in fixture_by_key:
            raise ValueError("audited scorer-v2 fact fixture keys are duplicated")
        fixture_by_key[key] = row

    by_case = {str(record["case_id"]): record for record in records}
    citation_numerator = 0
    citation_denominator = 0
    recognized_count = 0
    supported_count = 0
    expected_count = 0
    nonrecognition_count = 0
    correct_gate_count = 0
    accepted_evidence_turns = 0
    accepted_evidence_with_citations = 0
    safe_fallback_count = 0
    latencies: list[float] = []
    cost_observations = 0
    trace_counts = {
        "extractive_mode_case_count": 0,
        "no_evidence_path_case_count": 0,
        "tool_path_case_count": 0,
        "malformed_structured_response_count": 0,
        "proposed_claim_count": 0,
        "accepted_claim_count": 0,
        "invalid_handle_rejection_count": 0,
        "excerpt_mismatch_rejection_count": 0,
        "claim_not_substring_rejection_count": 0,
        "all_claims_rejected_fallback_count": 0,
    }

    for case in cases:
        record = by_case[case.case_id]
        citations = [str(item) for item in record.get("public_citations", [])]
        case_citations = citation_precision(citations, _judgments(case))
        citation_numerator += case_citations.numerator
        citation_denominator += case_citations.denominator
        answer = str(record.get("final_answer", ""))
        safe_fallback_count += int(answer.strip() == SAFE_GROUNDING_FALLBACK)
        cited_locators = set(citations)

        for fact in case.expected_facts:
            key = f"{case.case_id}::{fact.fact_id}"
            fixture = fixture_by_key.get(key)
            if fixture is None:
                raise ValueError(f"P4 scorer-v2 fixture is missing benchmark fact {key}")
            _validate_p4_fixture_for_fact(fixture, case, fact, key)
            paraphrases = fixture["positive_paraphrases"]
            assessment = classify_labeled_fact_assertion(
                answer,
                list(fact.aliases),
                positive_paraphrases=paraphrases,
            )
            expected_count += 1
            if not assessment.recognized:
                nonrecognition_count += 1
                continue
            recognized_count += 1
            supporting = {
                (
                    f"{locator.document_slug}|{locator.document_version}|"
                    f"{locator.section}|{locator.chunk_index}"
                )
                for locator in fact.supporting_locators
            }
            supported_count += int(bool(cited_locators & supporting))

        top_score = record.get("top_confidence_score")
        accepted = (
            score_meets_threshold(float(top_score), threshold) if top_score is not None else False
        )
        correct_gate_count += int(accepted == case.answerable)
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

        latency = record.get("answer_latency_ms")
        if isinstance(latency, int | float) and not isinstance(latency, bool):
            latencies.append(float(latency))
        cost_observations += int(record.get("cost_usd") is not None)
        _accumulate_p4_trace_counts(trace_counts, record.get("p4_diagnostics"))

    return {
        "scorer_version": "rag-v0.2-scorer-v2",
        "citation_precision": MetricResult(
            numerator=citation_numerator,
            denominator=citation_denominator,
            value=(citation_numerator / citation_denominator if citation_denominator else None),
        ).as_dict(),
        "groundedness": MetricResult(
            numerator=supported_count,
            denominator=recognized_count,
            value=(supported_count / recognized_count if recognized_count else None),
        ).as_dict(),
        "unsupported_claim_rate": (
            (recognized_count - supported_count) / recognized_count if recognized_count else None
        ),
        "expected_fact_coverage": MetricResult(
            numerator=recognized_count,
            denominator=expected_count,
            value=(recognized_count / expected_count if expected_count else None),
        ).as_dict(),
        "retrieval_evidence_gate_accuracy": MetricResult(
            numerator=correct_gate_count,
            denominator=len(cases),
            value=(correct_gate_count / len(cases) if cases else None),
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
        "repair_attempts": 0,
        "repair_successes": 0,
        "repair_failures": 0,
        "repair_model_latency_p50_ms": None,
        "repair_model_latency_p95_ms": None,
        "repair_cost_total_usd": None,
        "repair_cost_mean_usd_over_costed_attempts": None,
        "repair_cost_observations": 0,
        "recognized_fact_units": recognized_count,
        "unsupported_fact_units": recognized_count - supported_count,
        "scorer_v2_nonrecognition_count": nonrecognition_count,
        "p4_diagnostics": {
            **trace_counts,
            "fabricated_or_non_supplied_evidence_handle_count": trace_counts[
                "invalid_handle_rejection_count"
            ],
            "zero_fabricated_or_non_supplied_evidence_handles": (
                trace_counts["invalid_handle_rejection_count"] == 0
            ),
        },
    }


def score_p5_grounded_records(
    cases: Sequence[RagV02Case],
    records: Sequence[Mapping[str, Any]],
    threshold: float,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Score P5 using the same fact-specific scorer-v2 path without changing history."""

    p4_compatible_records: list[dict[str, Any]] = []
    for record in records:
        p5_diagnostics = record.get("p5_diagnostics")
        if not isinstance(p5_diagnostics, Mapping) or set(p5_diagnostics) != P5_TRACE_FIELDS:
            raise ValueError("P5 scoring requires the frozen P5 diagnostic field contract")
        if (
            p5_diagnostics.get("knowledge_terminal_output_transport")
            != P5_KNOWLEDGE_TERMINAL_OUTPUT_TRANSPORT
            or p5_diagnostics.get("provider_response_format_attached") is not False
        ):
            raise ValueError("P5 diagnostics do not match the frozen request transport")
        p4_compatible_records.append(
            {
                **dict(record),
                "p4_diagnostics": _p5_diagnostics_for_shared_scorer(p5_diagnostics),
            }
        )

    report = score_p4_grounded_records(cases, p4_compatible_records, threshold, repo_root=repo_root)
    report["p5_diagnostics"] = report.pop("p4_diagnostics")
    return report


def _p5_diagnostics_for_shared_scorer(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Map P5 trace names to the already-tested shared extractive scorer inputs."""

    active = raw.get("knowledge_mode_active")
    tool_path = raw.get("tool_path_entered")
    if not isinstance(active, bool) or not isinstance(tool_path, bool) or (active and tool_path):
        raise ValueError("P5 trace mode diagnostics are malformed")
    if raw.get("extractive_mode_deactivated_after_tool") is not tool_path:
        raise ValueError("P5 tool-path diagnostics are inconsistent")

    parse_success = raw.get("json_parse_success")
    schema_valid = raw.get("schema_validation_result")
    json_failure = raw.get("json_parse_failure_reason")
    if active:
        if parse_success is True and schema_valid is True:
            p4_parse_success = True
            p4_parse_failure = None
        elif parse_success is True and schema_valid is False:
            p4_parse_success = False
            p4_parse_failure = "invalid_p4_schema"
        elif parse_success is False and schema_valid is None:
            p4_parse_success = False
            p4_parse_failure = json_failure
        else:
            raise ValueError("P5 parse and schema diagnostics are inconsistent")
        mode_reason = (
            "malformed_or_invalid_structured_knowledge_output"
            if not p4_parse_success
            else "all_claims_rejected_safe_fallback"
            if all(
                value is not None
                for value in raw.get("deterministic_rejection_reason_per_claim", [])
            )
            else "terminal_knowledge_answer_validated"
        )
    else:
        p4_parse_success = None
        p4_parse_failure = None
        mode_reason = (
            "terminal_tool_answer_bypassed_validator"
            if tool_path
            else "no_selected_knowledge_evidence"
        )

    return {
        "raw_structured_model_response": raw.get("raw_terminal_content"),
        "parse_success": p4_parse_success,
        "parse_failure_reason": p4_parse_failure,
        "proposed_claims": raw.get("proposed_claims"),
        "proposed_evidence_handle_per_claim": raw.get("proposed_evidence_handle_per_claim"),
        "proposed_excerpt_per_claim": raw.get("proposed_excerpt_per_claim"),
        "handle_validation_result_per_claim": raw.get("handle_validation_result_per_claim"),
        "excerpt_validation_result_per_claim": raw.get("excerpt_validation_result_per_claim"),
        "deterministic_rejection_reason_per_claim": raw.get(
            "deterministic_rejection_reason_per_claim"
        ),
        "rendered_final_claims": raw.get("rendered_final_claims"),
        "p4_extractive_mode_active": active,
        "p4_extractive_mode_reason": mode_reason,
        "tool_path_entered": tool_path,
        "p4_extractive_mode_deactivated_after_tool": tool_path,
        "fallback_used": raw.get("fallback_used"),
        "fallback_reason": raw.get("fallback_reason"),
    }


def _validate_p4_fixture_for_fact(
    fixture: Mapping[str, Any], case: RagV02Case, fact: Any, key: str
) -> None:
    if fixture.get("case_id") != case.case_id or fixture.get("fact_id") != fact.fact_id:
        raise ValueError(f"P4 scorer-v2 fixture key does not match benchmark fact {key}")
    if fixture.get("statement") != fact.statement:
        raise ValueError(f"P4 scorer-v2 fixture statement differs from benchmark fact {key}")
    if fixture.get("benchmark_aliases") != list(fact.aliases):
        raise ValueError(f"P4 scorer-v2 fixture aliases differ from benchmark fact {key}")
    locator = fixture.get("supporting_locator")
    valid_locators = [item.model_dump() for item in fact.supporting_locators]
    if not isinstance(locator, dict) or locator not in valid_locators:
        raise ValueError(f"P4 scorer-v2 fixture locator differs from benchmark fact {key}")
    if fixture.get("category") != case.category:
        raise ValueError(f"P4 scorer-v2 fixture category differs from benchmark fact {key}")
    paraphrases = fixture.get("positive_paraphrases")
    if (
        not isinstance(paraphrases, list)
        or not paraphrases
        or any(not isinstance(item, str) or not item.strip() for item in paraphrases)
    ):
        raise ValueError(f"P4 scorer-v2 fixture paraphrases are invalid for benchmark fact {key}")


def _accumulate_p4_trace_counts(counts: dict[str, int], raw: Any) -> None:
    if not isinstance(raw, Mapping):
        raise ValueError("P4 scorer requires validated per-case trace diagnostics")
    required_fields, allowed_reasons = frozen_p4_observability_contract()
    if set(raw) != required_fields:
        raise ValueError("P4 scorer diagnostics do not match the frozen observability contract")
    active = raw.get("p4_extractive_mode_active")
    reason = raw.get("p4_extractive_mode_reason")
    tool_path = raw.get("tool_path_entered")
    deactivated = raw.get("p4_extractive_mode_deactivated_after_tool")
    if (
        not isinstance(active, bool)
        or not isinstance(tool_path, bool)
        or not isinstance(deactivated, bool)
        or deactivated != tool_path
    ):
        raise ValueError("P4 per-case trace mode diagnostics are malformed")
    if not isinstance(reason, str) or reason not in allowed_reasons:
        raise ValueError("P4 per-case trace mode reason is malformed")
    rejection_projection = raw.get("deterministic_rejection_reason_per_claim")
    expected_reason = (
        "terminal_tool_answer_bypassed_validator"
        if tool_path
        else (
            "malformed_or_invalid_structured_knowledge_output"
            if active and raw.get("parse_success") is False
            else "all_claims_rejected_safe_fallback"
            if active
            and raw.get("parse_success") is True
            and isinstance(rejection_projection, list)
            and all(value is not None for value in rejection_projection)
            else "terminal_knowledge_answer_validated"
            if active
            else "no_selected_knowledge_evidence"
        )
    )
    if reason != expected_reason or (active and tool_path):
        raise ValueError("P4 terminal mode diagnostics are inconsistent")
    counts["extractive_mode_case_count"] += int(active)
    counts["no_evidence_path_case_count"] += int(reason == "no_selected_knowledge_evidence")
    counts["tool_path_case_count"] += int(tool_path)
    if not active:
        if (
            raw.get("raw_structured_model_response") is not None
            or raw.get("parse_success") is not None
            or raw.get("parse_failure_reason") is not None
            or raw.get("proposed_claims") != []
            or raw.get("proposed_evidence_handle_per_claim") != []
            or raw.get("proposed_excerpt_per_claim") != []
            or raw.get("handle_validation_result_per_claim") != []
            or raw.get("excerpt_validation_result_per_claim") != []
            or raw.get("deterministic_rejection_reason_per_claim") != []
            or raw.get("rendered_final_claims") != ""
            or raw.get("fallback_used") is not False
            or raw.get("fallback_reason") is not None
        ):
            raise ValueError("P4 inactive-mode diagnostics contain response data")
        return
    if not isinstance(raw.get("parse_success"), bool):
        raise ValueError("P4 per-case parse diagnostics are malformed")
    counts["malformed_structured_response_count"] += int(not raw["parse_success"])
    proposed = raw.get("proposed_claims")
    handles = raw.get("proposed_evidence_handle_per_claim")
    excerpts = raw.get("proposed_excerpt_per_claim")
    handle_results = raw.get("handle_validation_result_per_claim")
    excerpt_results = raw.get("excerpt_validation_result_per_claim")
    rejection_reasons = raw.get("deterministic_rejection_reason_per_claim")
    if (
        not isinstance(proposed, list)
        or not isinstance(handles, list)
        or not isinstance(excerpts, list)
        or not isinstance(handle_results, list)
        or not isinstance(excerpt_results, list)
        or not isinstance(rejection_reasons, list)
    ):
        raise ValueError("P4 per-case claim diagnostics are malformed")
    if any(
        not isinstance(claim, Mapping)
        or set(claim) != _P4_CLAIM_DIAGNOSTIC_FIELDS
        or any(not isinstance(claim[field], str) for field in _P4_CLAIM_DIAGNOSTIC_FIELDS)
        for claim in proposed
    ):
        raise ValueError("P4 per-case proposed claims are malformed")
    if any(
        len(items) != len(proposed)
        for items in (handles, excerpts, handle_results, excerpt_results, rejection_reasons)
    ):
        raise ValueError("P4 per-case claim diagnostic arrays are inconsistent")
    if handles != [claim["evidence_handle"] for claim in proposed] or excerpts != [
        claim["supporting_excerpt"] for claim in proposed
    ]:
        raise ValueError("P4 per-case projection arrays do not match proposed claims")
    if any(not isinstance(value, bool) for value in handle_results):
        raise ValueError("P4 per-case handle validations are malformed")
    accepted_count = sum(value is None for value in rejection_reasons)
    counts["proposed_claim_count"] += len(proposed)
    counts["accepted_claim_count"] += accepted_count
    counts["invalid_handle_rejection_count"] += sum(
        reason == "invalid_handle" for reason in rejection_reasons
    )
    counts["excerpt_mismatch_rejection_count"] += sum(
        reason == "excerpt_mismatch" for reason in rejection_reasons
    )
    counts["claim_not_substring_rejection_count"] += sum(
        reason == "claim_not_substring" for reason in rejection_reasons
    )
    counts["all_claims_rejected_fallback_count"] += int(
        reason == "all_claims_rejected_safe_fallback"
    )


__all__ = [
    "GroundedExecutionAdapter",
    "M5dCaseExecutionError",
    "run_grounded_evaluation",
    "score_grounded_records",
    "score_p4_grounded_records",
]
