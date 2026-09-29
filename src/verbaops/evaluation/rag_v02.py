"""Independent, provider-free audit contracts for rag-v0.2."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from verbaops.evaluation.rag_models import ExpectedFact, RelevanceJudgment
from verbaops.knowledge.chunking import MAX_CHUNK_TOKENS, OVERLAP_TOKENS, chunk_sections
from verbaops.knowledge.parsing import detect_sections, normalize_markdown


class RagV02Error(ValueError):
    """Raised when a rag-v0.2 corpus or provenance contract is invalid."""


class RagV02Case(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    dataset_version: Literal["rag-v0.2"]
    split: Literal["dev", "release_holdout"]
    language: Literal["en"]
    category: Literal[
        "shipping",
        "returns",
        "refunds",
        "warranty",
        "payments",
        "privacy",
        "product-guides",
        "faq",
        "no-answer",
    ]
    query: str = Field(min_length=1)
    answerable: bool
    expected_answer: str = Field(min_length=1)
    relevance_judgments: tuple[RelevanceJudgment, ...]
    expected_facts: tuple[ExpectedFact, ...]

    @model_validator(mode="after")
    def validate_evidence_labels(self) -> RagV02Case:
        positive = [
            judgment for judgment in self.relevance_judgments if judgment.relevance_grade > 0
        ]
        if self.answerable and not positive:
            raise ValueError("answerable cases require positive relevance")
        if self.answerable and not self.expected_facts:
            raise ValueError("answerable cases require expected factual units")
        if not self.answerable and (positive or self.expected_facts):
            raise ValueError("no-answer cases cannot contain positive evidence or facts")
        return self


class RagV02SelectedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    gate: Literal[
        "G0_CURRENT_RRF",
        "G1_DENSE_SIMILARITY",
        "G2_TOP_EVIDENCE_CROSS_ENCODER",
    ]
    threshold: float
    grounding: Literal[
        "P0_CURRENT",
        "P1_PROMPT_V3",
        "P2_FAIL_CLOSED_CITATIONS",
        "P3_ONE_REPAIR_THEN_FAIL_CLOSED",
    ]
    model: Literal["M0", "M1"]

    @field_validator("threshold", mode="before")
    @classmethod
    def validate_finite_threshold(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("candidate threshold must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError("candidate threshold must be finite")
        return float(value)


class RagV02SelectionMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    answerable_acceptance: float = Field(ge=0, le=1)
    no_answer_rejection: float = Field(ge=0.9, le=1)
    citation_precision: float = Field(ge=0, le=1)
    labeled_groundedness: float = Field(ge=0, le=1)
    unsupported_recognized_fact_rate: float = Field(ge=0, le=1)
    expected_fact_coverage: float = Field(ge=0, le=1)
    answer_p95_latency_ms: float = Field(ge=0)


class RagV02DevEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    benchmark_version: Literal["rag-v0.2"]
    split: Literal["dev"]
    case_count: Literal[96]
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    knowledge_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    experiment_plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: str = Field(min_length=1)
    artifact_path: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluated_git_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    completed_at_utc: datetime
    selected_candidate: RagV02SelectedCandidate
    metrics: RagV02SelectionMetrics

    @field_validator("completed_at_utc")
    @classmethod
    def require_aware_completion_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("DEV completion time must include a UTC offset")
        return value

    @field_validator("artifact_path")
    @classmethod
    def require_relative_artifact_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(
                "DEV evidence artifact path must be relative and stay inside the repository"
            )
        return value


class RagV02SelectionArtifact(BaseModel):
    """Provenance schema required before a future v0.2 holdout can be opened."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    benchmark_version: Literal["rag-v0.2"]
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    knowledge_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    experiment_plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_gate: Literal[
        "G0_CURRENT_RRF",
        "G1_DENSE_SIMILARITY",
        "G2_TOP_EVIDENCE_CROSS_ENCODER",
    ]
    selected_gate_threshold: float
    selected_grounding_candidate: Literal[
        "P0_CURRENT",
        "P1_PROMPT_V3",
        "P2_FAIL_CLOSED_CITATIONS",
        "P3_ONE_REPAIR_THEN_FAIL_CLOSED",
    ]
    selected_model_candidate: Literal["M0", "M1"]
    retrieval_profile_version: str = Field(min_length=1)
    agent_prompt_version: str = Field(min_length=1)
    agent_graph_version: str = Field(min_length=1)
    selection_git_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    selected_at_utc: datetime
    selected_before_holdout: Literal[True]
    dev_evidence: RagV02DevEvidence

    @field_validator("selected_gate_threshold", mode="before")
    @classmethod
    def validate_finite_threshold(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("selected gate threshold must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError("selected gate threshold must be finite")
        return float(value)

    @field_validator("selected_at_utc")
    @classmethod
    def require_aware_selection_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("selection time must include a UTC offset")
        return value

    @model_validator(mode="after")
    def validate_dev_selection_provenance(self) -> RagV02SelectionArtifact:
        candidate = self.dev_evidence.selected_candidate
        if (
            self.dev_evidence.dataset_sha256 != self.dataset_sha256
            or self.dev_evidence.knowledge_manifest_sha256 != self.knowledge_manifest_sha256
            or self.dev_evidence.experiment_plan_sha256 != self.experiment_plan_sha256
        ):
            raise ValueError("DEV evidence hashes do not match the selection artifact")
        if (
            candidate.gate != self.selected_gate
            or candidate.threshold != self.selected_gate_threshold
            or candidate.grounding != self.selected_grounding_candidate
            or candidate.model != self.selected_model_candidate
        ):
            raise ValueError("DEV evidence candidate does not match the selected candidate")
        if self.dev_evidence.completed_at_utc >= self.selected_at_utc:
            raise ValueError("DEV evidence must complete before candidate selection")
        return self


class RagV02Audit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version: str
    case_count: int
    split_counts: dict[str, int]
    category_split_counts: dict[str, dict[str, int]]
    dataset_sha256: str
    manifest_sha256: str
    knowledge_manifest_sha256: str
    chunk_count: int
    normalized_v01_query_overlap_count: int


EXPECTED_CATEGORY_SPLITS: dict[str, dict[str, int]] = {
    "shipping": {"dev": 10, "release_holdout": 2},
    "returns": {"dev": 10, "release_holdout": 2},
    "refunds": {"dev": 8, "release_holdout": 2},
    "warranty": {"dev": 8, "release_holdout": 2},
    "payments": {"dev": 6, "release_holdout": 2},
    "privacy": {"dev": 5, "release_holdout": 1},
    "product-guides": {"dev": 13, "release_holdout": 3},
    "faq": {"dev": 12, "release_holdout": 4},
    "no-answer": {"dev": 24, "release_holdout": 6},
}
EXPECTED_SPLITS = {"dev": 96, "release_holdout": 24}
RAG_V02_PATH = Path("evals/rag/v0.2")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_query(value: str) -> str:
    """Normalize case, compatibility characters, punctuation, and spacing."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    kept = [
        character
        for character in normalized
        if not unicodedata.category(character).startswith(("P", "S"))
    ]
    return " ".join("".join(kept).split())


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    kept = [
        character if character.isalnum() or character.isspace() else " " for character in normalized
    ]
    return " ".join("".join(kept).split())


_ASSERTION_NEGATION_PATTERNS = (
    re.compile(
        r"\b(?:cannot|can not|unable to|not able to)\s+(?:verify|confirm|say|determine|establish|state)\b"
    ),
    re.compile(r"\b(?:do|does|did) not\s+(?:confirm|verify|say|state|support|establish|prove)\b"),
    re.compile(r"\b(?:do|does|did) not have enough\b.*\bto say\b"),
    re.compile(r"\b(?:do|does|did) not know\b.*\b(?:whether|if)\b"),
    re.compile(r"\b(?:not confirmed|not verified|unconfirmed|unverified)\b"),
    re.compile(r"\b(?:insufficient|inadequate) (?:evidence|company information|information)\b"),
)


def _normalize_assertion_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().replace("\u2019", "'")
    normalized = re.sub(r"\bcan't\b", "cannot", normalized)
    normalized = re.sub(r"\b(can not)\b", "cannot", normalized)
    normalized = re.sub(
        r"\b(don't|doesn't|didn't)\b", lambda match: f"{match.group(1)[:-3]} not", normalized
    )
    kept = [
        character if character.isalnum() or character.isspace() else " " for character in normalized
    ]
    return " ".join("".join(kept).split())


def recognize_labeled_fact_assertion(answer: str, aliases: Sequence[str]) -> bool:
    """Match only supplied benchmark fact aliases, excluding simple refusal/negation mentions."""

    if not answer or not aliases:
        return False
    for clause in re.split(r"(?<=[.!?;])\s+|[\r\n]+", answer):
        normalized_clause = _normalize_assertion_text(clause)
        for alias in aliases:
            normalized_alias = _normalize_assertion_text(alias)
            if not normalized_alias:
                continue
            pattern = re.compile(rf"(?<!\w){re.escape(normalized_alias)}(?!\w)")
            for match in pattern.finditer(normalized_clause):
                prefix = normalized_clause[: match.start()]
                prefix = re.split(r"\b(?:but|however|yet|although)\b", prefix)[-1]
                if not any(negation.search(prefix) for negation in _ASSERTION_NEGATION_PATTERNS):
                    return True
    return False


def load_rag_v02_cases(path: Path) -> tuple[RagV02Case, ...]:
    cases: list[RagV02Case] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RagV02Error(f"cannot read rag-v0.2 dataset: {error}") from error
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            raise RagV02Error(f"line {line_number}: blank lines are not allowed")
        try:
            cases.append(RagV02Case.model_validate_json(line))
        except (ValidationError, ValueError) as error:
            raise RagV02Error(f"line {line_number}: invalid rag-v0.2 case: {error}") from error
    return tuple(cases)


def _load_known_chunks(root: Path) -> tuple[dict[tuple[str, str, str, int], str], str]:
    corpus_root = root / "knowledge" / "novacommerce"
    manifest_path = corpus_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RagV02Error(f"knowledge manifest could not be loaded: {error}") from error
    chunks: dict[tuple[str, str, str, int], str] = {}
    for entry in manifest["documents"]:
        source = corpus_root / entry["path"]
        sections = detect_sections(normalize_markdown(source.read_bytes()))
        for chunk in chunk_sections(sections):
            key = (entry["slug"], entry["version"], chunk.section, chunk.chunk_index)
            chunks[key] = chunk.content
    return chunks, sha256_file(manifest_path)


def _validate_plan_shape(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise RagV02Error("experiment plan must be a JSON object")
    exact_ids = {
        "evidence_gates": [
            "G0_CURRENT_RRF",
            "G1_DENSE_SIMILARITY",
            "G2_TOP_EVIDENCE_CROSS_ENCODER",
        ],
        "grounding_candidates": [
            "P0_CURRENT",
            "P1_PROMPT_V3",
            "P2_FAIL_CLOSED_CITATIONS",
            "P3_ONE_REPAIR_THEN_FAIL_CLOSED",
        ],
        "model_candidates": ["M0", "M1"],
    }
    for key, identifiers in exact_ids.items():
        items = plan.get(key)
        if (
            not isinstance(items, list)
            or [item.get("id") for item in items if isinstance(item, dict)] != identifiers
        ):
            raise RagV02Error(f"experiment plan {key} identifiers do not match preregistration")
    rules = [
        "minimum_no_answer_rejection_90_percent",
        "maximize_answerable_acceptance",
        "within_2_percentage_points_prefer_lower_p95_latency",
        "then_prefer_fewer_inference_components_and_simpler_behavior",
        "never_use_release_holdout",
    ]
    if plan.get("evidence_gate_selection", {}).get("ordered_rules") != rules:
        raise RagV02Error("experiment plan evidence-gate selection order changed")
    if plan.get("evidence_gate_selection", {}).get("answerable_acceptance_target") != 0.7:
        raise RagV02Error("experiment plan answerable acceptance target must be 70 percent")
    if (
        plan["evidence_gate_selection"].get("minimum_dev_no_answer_rejection") != 0.9
        or plan["evidence_gate_selection"].get("answerable_acceptance_tie_band") != 0.02
        or plan["evidence_gate_selection"].get("tie_band_unit") != "percentage_points"
        or "p95_latency_tie_band" in plan["evidence_gate_selection"]
        or plan["evidence_gate_selection"].get("no_learned_combined_classifier") is not True
    ):
        raise RagV02Error("experiment plan evidence-gate guardrails changed")
    priorities = [
        "trust_security_invariants",
        "citation_precision",
        "labeled_groundedness_and_unsupported_units",
        "expected_fact_coverage",
        "answer_latency",
        "provider_cost",
    ]
    if plan.get("grounding_selection_priorities") != priorities:
        raise RagV02Error("experiment plan grounding selection priorities changed")
    if (
        plan.get("dataset_version") != "rag-v0.2"
        or plan.get("status") != "preregistered_not_results"
    ):
        raise RagV02Error("experiment plan must be a preregistration for rag-v0.2")
    if plan.get("schema_version") != "m5d-experiment-plan-v1":
        raise RagV02Error("experiment plan schema version is unsupported")
    for key in ("evidence_gate_selection", "model_selection_guard", "evaluator"):
        if not isinstance(plan.get(key), dict):
            raise RagV02Error(f"experiment plan {key} must be an object")
    gates = {item["id"]: item for item in plan["evidence_gates"]}
    if (
        gates["G0_CURRENT_RRF"].get("role") != "control_only"
        or gates["G0_CURRENT_RRF"].get("production_use") is not False
        or gates["G0_CURRENT_RRF"].get("score") != "frozen hybrid_rrf top score using k=60"
    ):
        raise RagV02Error("G0 must be control only")
    if (
        gates["G1_DENSE_SIMILARITY"].get("score_location")
        != "For each of the frozen final five hybrid evidence candidates, compute E5 cosine similarity between the existing query embedding and that candidate's stored document embedding, including lexical entrants without a dense rank; do not change ranking."
        or gates["G1_DENSE_SIMILARITY"].get("production_use") is not False
    ):
        raise RagV02Error("G1 must score the supplied final evidence candidates")
    rationale = gates["G2_TOP_EVIDENCE_CROSS_ENCODER"].get("top_n_rationale")
    if (
        gates["G2_TOP_EVIDENCE_CROSS_ENCODER"].get("top_n") != 5
        or gates["G2_TOP_EVIDENCE_CROSS_ENCODER"].get("changes_ranking") is not False
        or gates["G2_TOP_EVIDENCE_CROSS_ENCODER"].get("production_use") is not False
        or gates["G2_TOP_EVIDENCE_CROSS_ENCODER"].get("cross_encoder_model")
        != "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
        or gates["G2_TOP_EVIDENCE_CROSS_ENCODER"].get("cross_encoder_revision")
        != "1427fd652930e4ba29e8149678df786c240d8825"
        or not isinstance(rationale, str)
        or "exact same final five hybrid evidence candidates" not in rationale
    ):
        raise RagV02Error(
            "G2 must gate the pinned cross-encoder scores on the same five candidates"
        )
    expected_confidence_contract = {
        "ranking_and_candidates": "Keep the frozen hybrid_rrf ranking and the exact same final top-five evidence candidates for G0, G1, and G2.",
        "one_query_one_scalar": True,
        "threshold_acceptance": "score >= threshold",
        "threshold_rejection": "score < threshold",
        "thresholds_candidate_specific": True,
        "compare_raw_scores_across_candidates": False,
        "query_confidence_by_candidate": {
            "G0_CURRENT_RRF": "Frozen top hybrid-RRF score for the query from knowledge-retrieval-v1.1.",
            "G1_DENSE_SIMILARITY": "Maximum E5 cosine similarity between the existing query embedding and stored document embeddings for exactly the same final five hybrid evidence candidates, including candidates that entered through lexical retrieval and had no dense rank.",
            "G2_TOP_EVIDENCE_CROSS_ENCODER": "Maximum relevance score from cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 revision 1427fd652930e4ba29e8149678df786c240d8825 over exactly the same final five hybrid evidence candidates.",
        },
    }
    if plan.get("evidence_gate_confidence") != expected_confidence_contract:
        raise RagV02Error("experiment plan query-level gate confidence semantics changed")
    expected_selection_fields = [
        "benchmark_version",
        "dataset_sha256",
        "knowledge_manifest_sha256",
        "experiment_plan_sha256",
        "selected_gate",
        "selected_gate_threshold",
        "selected_grounding_candidate",
        "selected_model_candidate",
        "retrieval_profile_version",
        "agent_prompt_version",
        "agent_graph_version",
        "selection_git_sha",
        "selected_at_utc",
        "selected_before_holdout",
        "dev_evidence",
    ]
    expected_dev_evidence_fields = [
        "benchmark_version",
        "split",
        "case_count",
        "dataset_sha256",
        "knowledge_manifest_sha256",
        "experiment_plan_sha256",
        "run_id",
        "artifact_path",
        "artifact_sha256",
        "evaluated_git_sha",
        "completed_at_utc",
        "selected_candidate",
        "metrics",
    ]
    expected_selection_contract = {
        "required_fields": expected_selection_fields,
        "selected_gate_ids": exact_ids["evidence_gates"],
        "selected_grounding_candidate_ids": exact_ids["grounding_candidates"],
        "selected_model_candidate_ids": exact_ids["model_candidates"],
        "dev_evidence_required_fields": expected_dev_evidence_fields,
        "dev_evidence_contract": {
            "benchmark_version": "rag-v0.2",
            "split": "dev",
            "case_count": 96,
            "sha256_fields": [
                "dataset_sha256",
                "knowledge_manifest_sha256",
                "experiment_plan_sha256",
                "artifact_sha256",
            ],
            "minimum_no_answer_rejection": 0.9,
            "selected_candidate_must_match_top_level": True,
            "dev_evidence_hashes_must_match_selection": True,
            "artifact_path_must_be_relative_and_confined": True,
            "evaluated_git_sha_must_be_40_hex": True,
            "completion_time_must_have_utc_offset": True,
            "selection_time_must_follow_dev_completion": True,
            "selection_must_precede_holdout": True,
            "dev_artifact_sha256_required": True,
        },
        "field_constraints": {
            "sha256_format": "64 lowercase hexadecimal characters and must match current dataset, knowledge manifest, and experiment plan",
            "selected_gate_threshold": "finite numeric; threshold scale is candidate-specific",
            "selection_git_sha": "40 lowercase hexadecimal characters",
            "selected_at_utc": "timezone-aware timestamp after DEV completion",
            "selected_before_holdout": True,
            "profile_prompt_graph_versions": "non-empty strings",
            "model_candidate": "must be in the preregistered model candidate identifiers",
        },
    }
    if plan.get("future_selection_artifact_contract") != expected_selection_contract:
        raise RagV02Error("future selection artifact provenance contract changed")
    grounding = {item["id"]: item for item in plan["grounding_candidates"]}
    expected_grounding = {
        "P0_CURRENT": "Current system_v2 plus current finalizer.",
        "P1_PROMPT_V3": "P0 with a stronger knowledge-grounding prompt only.",
        "P2_FAIL_CLOSED_CITATIONS": "P1 plus deterministic protection for pure knowledge turns where evidence was accepted but no valid citations were produced.",
        "P3_ONE_REPAIR_THEN_FAIL_CLOSED": "P2 plus at most one bounded model repair attempt for a missing-citation knowledge answer before deterministic fallback.",
    }
    if any(grounding[key].get("definition") != value for key, value in expected_grounding.items()):
        raise RagV02Error("grounding candidate definitions changed")
    models = {item["id"]: item for item in plan["model_candidates"]}
    if (
        models["M0"].get("model") != "groq/openai/gpt-oss-120b"
        or models["M0"].get("role") != "current_stage5_baseline"
        or models["M0"].get("production_change_in_m5d_a") is not False
    ):
        raise RagV02Error("M0 must describe the existing Stage 5 baseline")
    if (
        models["M1"].get("model") != "Qwen/Qwen3-30B-A3B-Instruct-2507"
        or models["M1"].get("role") != "open_weight_candidate"
        or models["M1"].get("preferred_serving") != "self-hosted OpenAI-compatible local endpoint"
        or models["M1"].get("production_change_in_m5d_a") is not False
        or models["M1"].get("hosted_ci_download") is not False
        or models["M1"].get("local_feasibility_status") != "M1_LOCAL_BLOCKED_RESOURCES"
    ):
        raise RagV02Error("M1 must name the preregistered Qwen open-weight candidate")
    guard = plan.get("model_selection_guard", {})
    if (
        guard.get("required_evaluations")
        != ["M5D rag-v0.2 DEV grounding evaluation", "Stage 4 DEV agent/tool/security evaluation"]
        or guard.get("stage4_release_holdout_for_tuning") is not False
        or guard.get("must_preserve")
        != [
            "exact five Commerce tools",
            "deterministic authorization boundaries",
            "zero S4 violations",
            "zero unauthorized actions",
            "tool-selection quality without material regression",
            "valid tool-argument behavior",
            "citation and grounding quality",
            "acceptable latency",
        ]
    ):
        raise RagV02Error("future model selection guard changed")
    if plan.get("evaluator", {}).get("llm_judge") is not False:
        raise RagV02Error("experiment plan must prohibit LLM judging")
    return plan


def validate_experiment_plan(path: Path) -> dict[str, Any]:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RagV02Error(f"experiment plan cannot be loaded: {error}") from error
    return _validate_plan_shape(plan)


def guard_rag_v02_split(
    split: str = "dev",
    *,
    selection_path: Path | None = None,
) -> str:
    """Permit DEV by default and require valid future selection provenance for holdout."""

    if split == "dev":
        return split
    if split != "release_holdout":
        raise RagV02Error(f"unsupported rag-v0.2 split: {split}")
    if selection_path is None:
        raise RagV02Error("release_holdout is sealed until a provenance-valid selection exists")
    try:
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RagV02Error(
            f"selection provenance artifact is missing or malformed: {error}"
        ) from error
    if not isinstance(selection, dict):
        raise RagV02Error("selection provenance must be a JSON object")
    try:
        root = Path(__file__).resolve().parents[3]
        dataset_sha = sha256_file(root / RAG_V02_PATH / "questions.jsonl")
        knowledge_sha = sha256_file(root / "knowledge/novacommerce/manifest.json")
        plan_path = root / RAG_V02_PATH / "experiment-plan.json"
        validate_experiment_plan(plan_path)
        plan_sha = sha256_file(plan_path)
    except OSError as error:
        raise RagV02Error(f"holdout provenance sources are unavailable: {error}") from error
    try:
        artifact = RagV02SelectionArtifact.model_validate(selection)
    except ValidationError as error:
        raise RagV02Error(f"selection provenance is incomplete or invalid: {error}") from error
    if (
        artifact.dataset_sha256 != dataset_sha
        or artifact.knowledge_manifest_sha256 != knowledge_sha
        or artifact.experiment_plan_sha256 != plan_sha
    ):
        raise RagV02Error("selection provenance is missing or mismatched")
    return split


def audit_rag_v02(
    root: Path,
    *,
    cases: list[dict[str, Any]] | tuple[RagV02Case, ...] | None = None,
) -> RagV02Audit:
    """Validate all v0.2 cases, locators, fact text, independent queries, and manifest SHAs."""

    dataset_path = root / RAG_V02_PATH / "questions.jsonl"
    manifest_path = root / RAG_V02_PATH / "manifest.json"
    if cases is None:
        typed_cases = load_rag_v02_cases(dataset_path)
    else:
        try:
            typed_cases = tuple(
                case if isinstance(case, RagV02Case) else RagV02Case.model_validate(case)
                for case in cases
            )
        except ValidationError as error:
            raise RagV02Error(f"invalid rag-v0.2 case: {error}") from error
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RagV02Error(f"rag-v0.2 manifest cannot be loaded: {error}") from error
    chunks, knowledge_sha = _load_known_chunks(root)
    errors: list[str] = []
    dataset_sha = sha256_file(dataset_path)
    if len(typed_cases) != 120:
        errors.append(f"case count expected 120, got {len(typed_cases)}")
    ids = [case.case_id for case in typed_cases]
    if len(ids) != len(set(ids)):
        errors.append("duplicate case IDs")
    normalized_queries = [normalize_query(case.query) for case in typed_cases]
    if len(normalized_queries) != len(set(normalized_queries)):
        errors.append("duplicate normalized queries")
    pairs = [
        (normalize_query(case.query), _normalize_text(case.expected_answer)) for case in typed_cases
    ]
    if len(pairs) != len(set(pairs)):
        errors.append("duplicate normalized expected-answer/query pairs")
    v01_path = root / "evals/rag/v0.1/questions.jsonl"
    v01_queries: set[str] = set()
    for line in v01_path.read_text(encoding="utf-8").splitlines():
        v01_queries.add(normalize_query(json.loads(line)["query"]))
    overlap = set(normalized_queries) & v01_queries
    if overlap:
        errors.append(f"normalized queries overlap rag-v0.1 ({len(overlap)} cases)")
    split_counts: Counter[str] = Counter(case.split for case in typed_cases)
    if dict(split_counts) != EXPECTED_SPLITS:
        errors.append(f"split counts expected {EXPECTED_SPLITS}, got {dict(split_counts)}")
    category_splits: dict[str, Counter[str]] = defaultdict(Counter)
    for case in typed_cases:
        category_splits[case.category][case.split] += 1
    observed_category_splits = {
        category: {
            "dev": category_splits[category]["dev"],
            "release_holdout": category_splits[category]["release_holdout"],
        }
        for category in EXPECTED_CATEGORY_SPLITS
    }
    if observed_category_splits != EXPECTED_CATEGORY_SPLITS:
        errors.append("category/split counts do not match the preregistered distribution")
    for case in typed_cases:
        judgment_keys: set[tuple[str, str, str, int]] = set()
        positive_keys: set[tuple[str, str, str, int]] = set()
        for judgment in case.relevance_judgments:
            key = judgment.key()
            judgment_keys.add(key)
            if key not in chunks:
                errors.append(f"{case.case_id}: invalid relevance locator {key}")
            if judgment.relevance_grade > 0:
                positive_keys.add(key)
        if case.answerable and not positive_keys:
            errors.append(f"{case.case_id}: answerable without positive relevance")
        if not case.answerable and positive_keys:
            errors.append(f"{case.case_id}: no-answer has positive relevance")
        for fact in case.expected_facts:
            supported = False
            for locator in fact.supporting_locators:
                key = locator.key()
                content = chunks.get(key)
                if content is None or key not in judgment_keys or key not in positive_keys:
                    continue
                if _normalize_text(fact.statement) in _normalize_text(content):
                    supported = True
            if not supported:
                errors.append(
                    f"{case.case_id}: expected fact has no valid supporting corpus text: {fact.fact_id}"
                )
    expected_manifest = {
        "dataset_version": "rag-v0.2",
        "language": "en",
        "expected_case_count": 120,
        "split_counts": EXPECTED_SPLITS,
        "category_split_counts": EXPECTED_CATEGORY_SPLITS,
        "questions_sha256": dataset_sha,
        "knowledge_manifest": "knowledge/novacommerce/manifest.json",
        "knowledge_manifest_sha256": knowledge_sha,
        "chunking": {"max_chunk_tokens": MAX_CHUNK_TOKENS, "overlap_tokens": OVERLAP_TOKENS},
    }
    for manifest_key, expected in expected_manifest.items():
        if manifest.get(manifest_key) != expected:
            errors.append(f"rag-v0.2 manifest {manifest_key} mismatch")
    plan_path = root / RAG_V02_PATH / "experiment-plan.json"
    try:
        validate_experiment_plan(plan_path)
    except RagV02Error as error:
        errors.append(str(error))
    if errors:
        raise RagV02Error("; ".join(errors))
    return RagV02Audit(
        dataset_version="rag-v0.2",
        case_count=len(typed_cases),
        split_counts={split: split_counts[split] for split in ("dev", "release_holdout")},
        category_split_counts={
            category: {
                "dev": observed_category_splits[category]["dev"],
                "release_holdout": observed_category_splits[category]["release_holdout"],
                "total": sum(observed_category_splits[category].values()),
            }
            for category in EXPECTED_CATEGORY_SPLITS
        },
        dataset_sha256=dataset_sha,
        manifest_sha256=sha256_file(manifest_path),
        knowledge_manifest_sha256=knowledge_sha,
        chunk_count=len(chunks),
        normalized_v01_query_overlap_count=len(overlap),
    )


__all__ = [
    "RagV02Audit",
    "RagV02Case",
    "RagV02Error",
    "RagV02SelectionArtifact",
    "audit_rag_v02",
    "guard_rag_v02_split",
    "load_rag_v02_cases",
    "normalize_query",
    "recognize_labeled_fact_assertion",
    "validate_experiment_plan",
]
