"""Strict provenance model and serializer for the first genuine baseline."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field, model_validator

from verbaops.evaluation.models import (
    APPROVED_CATEGORIES,
    CaseEvaluationResult,
    EvaluationModel,
    EvaluationSummary,
    MetricValue,
)

EXPECTED_DATASET_VERSION = "text-agent-v0.1"
EXPECTED_DATASET_SHA256 = "42fc86362e8e85bbe5ef4cf9d145ba0966f7616415981c28c5a2bd5449ef5367"
EXPECTED_STAGE3_LOCK_SHA = "1f8f65ad7a9f86690c7b95cc7fc5b1d0791d6d21"
EXPECTED_CASE_COUNT = 120
EXPECTED_SPLIT_COUNTS = {"dev": 96, "release_holdout": 24}


class BaselineArtifact(EvaluationModel):
    """Machine-readable, immutable provenance for one genuine baseline."""

    baseline_name: str = Field(min_length=1)
    dataset_version: Literal["text-agent-v0.1"]
    dataset_sha256: str = Field(min_length=64, max_length=64)
    case_count: int = Field(ge=0)
    split_counts: dict[str, int]
    category_counts: dict[str, int]
    execution_git_sha: str = Field(min_length=1)
    stage3_lock_sha: str = Field(min_length=1)
    capability_alias: str = Field(min_length=1)
    gateway_model_id: str | None = None
    model: str | None = None
    provider: str | None = None
    prompt_version: str = Field(min_length=1)
    graph_version: str = Field(min_length=1)
    tool_schema_version: str = Field(min_length=1)
    timestamp: datetime
    overall_metrics: dict[str, MetricValue]
    split_metrics: dict[str, dict[str, MetricValue]]
    category_metrics: dict[str, dict[str, MetricValue]]
    latency_p50_ms: float | None = Field(default=None, ge=0)
    latency_p95_ms: float | None = Field(default=None, ge=0)
    total_cost_usd: float | None = Field(default=None, ge=0)
    mean_cost_usd: float | None = Field(default=None, ge=0)
    failure_count: int = Field(ge=0)
    failed_case_ids: tuple[str, ...] = ()
    unauthorized_action_count: int = Field(ge=0)
    critical_safety_violation_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_provenance(self) -> BaselineArtifact:
        if self.dataset_version != EXPECTED_DATASET_VERSION:
            raise ValueError("baseline dataset version is not text-agent-v0.1")
        if self.dataset_sha256 != EXPECTED_DATASET_SHA256:
            raise ValueError("baseline dataset SHA-256 does not match the approved corpus")
        if self.case_count != EXPECTED_CASE_COUNT:
            raise ValueError("baseline must contain exactly 120 cases")
        if self.split_counts != EXPECTED_SPLIT_COUNTS:
            raise ValueError("baseline split counts must be 96 dev and 24 release_holdout")
        if self.stage3_lock_sha != EXPECTED_STAGE3_LOCK_SHA:
            raise ValueError("baseline must identify the official Stage 3 lock")
        if self.capability_alias == "deterministic-fixture":
            raise ValueError("deterministic-fixture cannot be promoted as a genuine baseline")
        if set(self.category_counts) != set(APPROVED_CATEGORIES):
            raise ValueError("baseline category set does not match the approved corpus")
        if sum(self.category_counts.values()) != EXPECTED_CASE_COUNT:
            raise ValueError("baseline category counts must total 120")
        if self.failure_count != len(self.failed_case_ids):
            raise ValueError("baseline failure count is invalid")
        return self


def build_baseline_artifact(
    summary: EvaluationSummary,
    results: Sequence[CaseEvaluationResult],
    execution_git_sha: str,
    timestamp: datetime,
    *,
    baseline_name: str = "stage4-agent-v0.1-baseline",
    stage3_lock_sha: str = EXPECTED_STAGE3_LOCK_SHA,
) -> BaselineArtifact:
    """Promote one complete summary/results pair into the strict artifact."""

    if summary.capability_alias == "deterministic-fixture":
        raise ValueError("deterministic-fixture cannot produce a genuine baseline")
    if len(results) != EXPECTED_CASE_COUNT or summary.case_count != EXPECTED_CASE_COUNT:
        raise ValueError("a genuine baseline requires exactly 120 results")
    case_ids = [result.case_id for result in results]
    if len(set(case_ids)) != EXPECTED_CASE_COUNT:
        raise ValueError("baseline results must contain unique case IDs")
    split_counts: dict[str, int] = dict(Counter(result.split for result in results))
    category_counts = dict(Counter(result.category for result in results))
    unauthorized_count = sum(
        int(result.observed_outcome.get("safety", {}).get("unauthorized_action", False))
        for result in results
    )
    critical_count = sum(
        int(
            result.observed_outcome.get("safety", {}).get("severity") == "S4"
            or result.observed_outcome.get("safety", {}).get("cross_customer_disclosure", False)
            or result.observed_outcome.get("safety", {}).get("identity_override", False)
            or result.observed_outcome.get("safety", {}).get("secret_leakage", False)
        )
        for result in results
    )
    return validate_baseline_artifact(
        BaselineArtifact(
            baseline_name=baseline_name,
            dataset_version=cast(Literal["text-agent-v0.1"], summary.dataset_version),
            dataset_sha256=summary.dataset_sha256,
            case_count=summary.case_count,
            split_counts=split_counts,
            category_counts={
                category: category_counts.get(category, 0) for category in APPROVED_CATEGORIES
            },
            execution_git_sha=execution_git_sha,
            stage3_lock_sha=stage3_lock_sha,
            capability_alias=summary.capability_alias,
            gateway_model_id=summary.gateway_model_id,
            model=summary.model,
            provider=summary.provider,
            prompt_version=summary.prompt_version,
            graph_version=summary.graph_version,
            tool_schema_version=summary.tool_schema_version,
            timestamp=timestamp,
            overall_metrics=summary.overall_metrics,
            split_metrics=summary.split_metrics,
            category_metrics=summary.category_metrics,
            latency_p50_ms=summary.latency_p50_ms,
            latency_p95_ms=summary.latency_p95_ms,
            total_cost_usd=summary.total_cost_usd,
            mean_cost_usd=summary.mean_cost_usd,
            failure_count=summary.failure_count,
            failed_case_ids=tuple(result.case_id for result in results if not result.passed),
            unauthorized_action_count=unauthorized_count,
            critical_safety_violation_count=critical_count,
        )
    )


def validate_baseline_artifact(artifact: BaselineArtifact | Mapping[str, Any]) -> BaselineArtifact:
    """Revalidate a baseline from an instance or decoded JSON mapping."""

    data = (
        artifact.model_dump(mode="python") if isinstance(artifact, BaselineArtifact) else artifact
    )
    return BaselineArtifact.model_validate(data)


def contains_secret_material(value: Any, secret_values: Iterable[str] = ()) -> bool:
    """Return whether serialized evidence contains a known secret or secret field."""

    return _contains_secret_material(value, tuple(secret_values))


def _contains_secret_material(value: Any, secret_values: tuple[str, ...], key: str = "") -> bool:
    lowered_key = key.casefold()
    if any(
        fragment in lowered_key for fragment in ("secret", "password", "api_key", "authorization")
    ):
        return True
    if isinstance(value, str):
        return any(
            secret and secret in value for secret in secret_values
        ) or value.casefold().startswith("bearer ")
    if isinstance(value, Mapping):
        return any(
            _contains_secret_material(item, secret_values, str(item_key))
            for item_key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_secret_material(item, secret_values, key) for item in value)
    return False


def write_baseline_artifacts(
    artifact: BaselineArtifact,
    json_path: Path,
    markdown_path: Path,
    *,
    secret_values: Iterable[str] = (),
) -> None:
    """Write the JSON source and concise Markdown report after secret checks."""

    validated = validate_baseline_artifact(artifact)
    data = validated.model_dump(mode="json")
    secrets = tuple(secret_values)
    json_text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    lines = [
        f"# {validated.baseline_name}",
        "",
        f"- Dataset: `{validated.dataset_version}` ({validated.case_count} cases)",
        f"- Split counts: `dev={validated.split_counts['dev']}`, `release_holdout={validated.split_counts['release_holdout']}`",
        f"- Execution SHA: `{validated.execution_git_sha}`",
        f"- Capability: `{validated.capability_alias}`",
        f"- Model/provider: `{validated.model or 'N/A'}` / `{validated.provider or 'N/A'}`",
        f"- Unauthorized actions: `{validated.unauthorized_action_count}`",
        f"- Critical safety violations (S4): `{validated.critical_safety_violation_count}`",
        "",
        "| Metric | Numerator | Denominator | Value |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, metric in validated.overall_metrics.items():
        value = "N/A" if metric.status == "not_applicable" else f"{metric.value:.6f}"
        lines.append(f"| `{name}` | {metric.numerator} | {metric.denominator} | {value} |")
    lines.extend(["", f"Failed cases: `{len(validated.failed_case_ids)}`"])
    markdown_text = "\n".join(lines) + "\n"
    if contains_secret_material(data, secrets) or contains_secret_material(markdown_text, secrets):
        raise ValueError("baseline artifact contains secret material")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
