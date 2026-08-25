"""Immutable application-owned models for deterministic evaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

APPROVED_TOOLS: tuple[str, ...] = (
    "get_order_status",
    "get_shipment_status",
    "get_refund_status",
    "search_products",
    "list_delivery_slots",
)
APPROVED_CATEGORIES: tuple[str, ...] = (
    "order-status",
    "shipment-status",
    "refund-status",
    "product-search",
    "delivery-slots",
    "missing-ambiguous-identifiers",
    "unsupported-write",
    "safety-injection-identity-cross-customer",
    "benign-no-tool",
)
OUTCOME_KINDS = (
    "clarify",
    "refuse",
    "grounded_tool_answer",
    "safe_not_found",
    "benign_response",
)


class EvaluationModel(BaseModel):
    """Common closed and immutable configuration for evaluation records."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class ConversationTurn(EvaluationModel):
    """One user-visible conversation turn used to establish case state."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ExpectedOutcome(EvaluationModel):
    """Typed expected result used by deterministic outcome scoring."""

    kind: Literal[
        "clarify",
        "refuse",
        "grounded_tool_answer",
        "safe_not_found",
        "benign_response",
    ]
    authoritative_facts: dict[str, Any] = Field(default_factory=dict)
    clarification_fields: tuple[str, ...] = ()
    not_found: bool = False

    @model_validator(mode="after")
    def validate_kind_fields(self) -> ExpectedOutcome:
        if self.kind == "clarify" and not self.clarification_fields:
            raise ValueError("clarify outcomes must name missing fields")
        if self.kind == "grounded_tool_answer" and not self.authoritative_facts:
            raise ValueError("grounded outcomes must name authoritative facts")
        if self.kind == "safe_not_found" and not self.not_found:
            raise ValueError("safe_not_found outcomes must set not_found")
        return self


class EvaluationCase(EvaluationModel):
    """One versioned case from the Stage 4 golden corpus."""

    case_id: str = Field(min_length=1)
    dataset_version: Literal["text-agent-v0.1"]
    split: Literal["dev", "release_holdout"]
    language: Literal["en"]
    category: str
    customer_id: UUID | None
    conversation: tuple[ConversationTurn, ...] = Field(min_length=1)
    expected_tool: str | None
    expected_arguments: dict[str, Any]
    expected_outcome: ExpectedOutcome
    requires_confirmation: Literal[False]
    forbidden_actions: tuple[str, ...]

    @model_validator(mode="after")
    def validate_case_shape(self) -> EvaluationCase:
        if self.category not in APPROVED_CATEGORIES:
            raise ValueError(f"unknown evaluation category: {self.category}")
        if self.expected_tool is not None and self.expected_tool not in APPROVED_TOOLS:
            raise ValueError(f"unknown evaluation tool: {self.expected_tool}")
        if self.expected_tool is None and self.expected_arguments:
            raise ValueError("no-tool cases must have empty expected_arguments")
        if not self.conversation or self.conversation[-1].role != "user":
            raise ValueError("conversation must end with a user turn")
        return self


class ObservedToolCall(EvaluationModel):
    """One business-tool call observed during a case execution."""

    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None
    succeeded: bool = True


class SafetyOutcome(EvaluationModel):
    """Observed safety classification for one evaluated case."""

    severity: Literal["S0", "S1", "S2", "S3", "S4"] = "S0"
    unauthorized_action: bool = False
    cross_customer_disclosure: bool = False
    identity_override: bool = False
    secret_leakage: bool = False


class EvaluationObservation(EvaluationModel):
    """Adapter-produced observation consumed by pure scoring functions."""

    observed_tools: tuple[ObservedToolCall, ...] = ()
    final_response: str = ""
    authoritative_tool_results: tuple[dict[str, Any], ...] = ()
    answer_facts: dict[str, Any] = Field(default_factory=dict)
    safety: SafetyOutcome = Field(default_factory=SafetyOutcome)
    capability_alias: str | None = None
    gateway_model_id: str | None = None
    model: str | None = None
    provider: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    agent_run_id: UUID | None = None
    started_at: datetime | None = None


class MetricValue(EvaluationModel):
    """Metric value with explicit numerator and denominator."""

    status: Literal["available", "not_applicable"]
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_value(self) -> MetricValue:
        if self.status == "not_applicable":
            if self.numerator != 0 or self.denominator != 0 or self.value is not None:
                raise ValueError("not applicable metrics must have zero counts and no value")
            return self
        if self.denominator == 0:
            raise ValueError("available metrics require a positive denominator")
        expected = self.numerator / self.denominator
        if self.value is None:
            object.__setattr__(self, "value", expected)
        elif abs(self.value - expected) > 1e-12:
            raise ValueError("metric value must equal numerator divided by denominator")
        return self


class CaseEvaluationResult(EvaluationModel):
    """Deterministic score for one corpus case."""

    case_id: str
    split: Literal["dev", "release_holdout"]
    category: str
    language: Literal["en"]
    passed: bool
    expected_tool: str | None
    observed_tools: tuple[str, ...]
    expected_arguments: dict[str, Any]
    observed_arguments: dict[str, Any]
    expected_outcome: ExpectedOutcome
    observed_outcome: dict[str, Any]
    metric_details: dict[str, MetricValue]
    failure_reasons: tuple[str, ...] = ()
    latency_ms: float | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    agent_run_id: UUID | None = None


class EvaluationRunMetadata(EvaluationModel):
    """Reproducibility metadata for one persisted or local evaluation run."""

    id: UUID
    dataset_version: str = Field(min_length=1)
    dataset_sha256: str = Field(min_length=64, max_length=64)
    git_sha: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    capability_alias: str = Field(min_length=1)
    gateway_model_id: str | None = None
    model: str | None = None
    provider: str | None = None
    prompt_version: str = Field(min_length=1)
    graph_version: str = Field(min_length=1)
    tool_schema_version: str = Field(min_length=1)
    status: Literal["running", "completed", "failed"] = "running"
    case_count: int = Field(ge=0)
    started_at: datetime
    completed_at: datetime | None = None
    summary: dict[str, Any] | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)


class EvaluationSummary(EvaluationModel):
    """Aggregated deterministic evaluation report."""

    run_id: UUID
    dataset_version: str
    dataset_sha256: str
    case_count: int = Field(ge=0)
    split_metrics: dict[str, dict[str, MetricValue]] = Field(default_factory=dict)
    category_metrics: dict[str, dict[str, MetricValue]] = Field(default_factory=dict)
    overall_metrics: dict[str, MetricValue] = Field(default_factory=dict)
    prompt_version: str
    graph_version: str
    tool_schema_version: str
    capability_alias: str
    gateway_model_id: str | None = None
    model: str | None = None
    provider: str | None = None
    latency_p50_ms: float | None = Field(default=None, ge=0)
    latency_p95_ms: float | None = Field(default=None, ge=0)
    total_cost_usd: float | None = Field(default=None, ge=0)
    mean_cost_usd: float | None = Field(default=None, ge=0)
    failure_count: int = Field(ge=0)
