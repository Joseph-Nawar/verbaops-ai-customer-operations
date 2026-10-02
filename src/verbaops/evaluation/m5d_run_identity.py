"""Small provenance helpers for canonical M5D-B DEV runs."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from verbaops.agent.evaluation import AgentEvaluationProfile, GroundingCandidate
from verbaops.retrieval.evidence_gate import EvidenceGate

_SHA1 = re.compile(r"^[a-f0-9]{40}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
PRE_EXPERIMENT_SHA = "347eccfd7aaa22332bdf36ee396715133b716b9c"
CANONICAL_APPLICATION_SHA = "7f82c565e7f9fc085f2d81c2c04a9861444837a1"
_IDENTITY_FIELDS = (
    "benchmark_version",
    "split",
    "dataset_sha256",
    "knowledge_manifest_sha256",
    "experiment_plan_sha256",
    "pre_experiment_sha",
    "evaluated_git_sha",
    "evidence_gate",
    "evidence_gate_threshold",
    "grounding_candidate",
    "model_candidate",
    "retrieval_profile_version",
    "agent_prompt_version",
    "agent_graph_version",
    "model_revision",
    "run_id",
)
_OPTIONAL_IDENTITY_FIELDS = ("evaluation_harness_sha",)
_P4_IDENTITY_FIELDS = (
    "scorer_version",
    "scorer_manifest_sha256",
    "scorer_fixture_sha256",
    "scorer_spec_sha256",
    "scorer_implementation_sha256",
    "scorer_definition_commit_sha",
    "p4_schema_sha256",
    "application_under_test_sha",
    "freeze_commit_sha",
    "hosted_ci_run_id",
    "hosted_ci_head_sha",
    "grounding_finalizer_version",
)
_P5_IDENTITY_FIELDS = (
    "p5_experiment_plan_sha256",
    "scorer_version",
    "scorer_definition_commit_sha",
    "scorer_implementation_sha256",
    "scorer_manifest_sha256",
    "scorer_fixture_sha256",
    "scorer_spec_sha256",
    "local_output_schema_sha256",
    "application_under_test_sha",
    "evaluation_harness_sha",
    "implementation_freeze_sha",
    "hosted_ci_run_id",
    "hosted_ci_head_sha",
    "hosted_ci_conclusion",
    "hosted_ci_job_conclusions_sha256",
    "provider",
    "capability_alias",
    "retrieval_strategy",
    "final_evidence_count",
    "agent_prompt_sha256",
    "grounding_finalizer_version",
    "knowledge_terminal_output_transport",
    "tool_choice",
    "provider_response_format_attached",
)
_GENERATED_ROOTS = (
    PurePosixPath("evals/rag/v0.2/dev-evidence/canonical"),
    PurePosixPath("artifacts/m5d"),
)
_APPROVED_HARNESS_PATHS = frozenset(
    {
        "scripts/run_m5d_grounded_eval.py",
        "scripts/run_m5d_api.py",
        "scripts/migrate_m5d_canonical_provenance.py",
        "src/verbaops/evaluation/m5d_run_identity.py",
        "tests/evaluation/test_m5d_provenance_correction.py",
        "tests/evaluation/test_m5d_run_identity.py",
        "docs/evaluation/stage5-m5d-b-dev-results.md",
        "evals/rag/v0.2/dev-decision.json",
        "evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json",
        "evals/rag/v0.2/dev-evidence/canonical/provider-smoke.json",
    }
)
_APPROVED_HARNESS_PREFIXES = ("evals/rag/v0.2/dev-evidence/canonical/",)
_CANONICAL_OUTPUT_ROOT = PurePosixPath("evals/rag/v0.2/dev-evidence/canonical")
_HARNESS_REVISION_PATHS = (
    "scripts/run_m5d_grounded_eval.py",
    "scripts/run_m5d_api.py",
    "scripts/migrate_m5d_canonical_provenance.py",
    "src/verbaops/evaluation/m5d_run_identity.py",
)
_MIGRATABLE_RUNS = {
    "canonical-M0-P0-20260929T124811Z-0d27c8d7": (
        "P0_CURRENT",
        "02e58b8d147551130714ff754372c304a2ec4253295bd79365920ec5730ac546",
        "text-agent-system-v2",
    ),
    "canonical-M0-P1-20260930T105712Z-c77394bd": (
        "P1_PROMPT_V3",
        "d79238b2a90b3b1cc1733c61f55632157a64268884d4ddb892deec0001ff182b",
        "text-agent-system-v3",
    ),
    "canonical-M0-P2-20260930T135336Z-7c951350": (
        "P2_FAIL_CLOSED_CITATIONS",
        "79b499049690baecf8bffcc49c1af1a64de00161828a29bce50d1792c899c772",
        "text-agent-system-v2",
    ),
}


def _validated_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in _IDENTITY_FIELDS if field not in identity]
    if missing:
        raise ValueError(f"M5D run identity is missing fields: {', '.join(missing)}")
    normalized = {field: identity[field] for field in _IDENTITY_FIELDS}
    for field in _OPTIONAL_IDENTITY_FIELDS:
        if field in identity:
            normalized[field] = identity[field]
    is_p4 = normalized.get("grounding_candidate") == "P4_EVIDENCE_LINKED_SINGLE_PASS"
    is_p5 = normalized.get("grounding_candidate") == "P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS"
    if is_p4:
        missing_p4 = [field for field in _P4_IDENTITY_FIELDS if field not in identity]
        if missing_p4:
            raise ValueError(f"P4 run identity is missing fields: {', '.join(missing_p4)}")
        normalized.update({field: identity[field] for field in _P4_IDENTITY_FIELDS})
    if is_p5:
        missing_p5 = [field for field in _P5_IDENTITY_FIELDS if field not in identity]
        if missing_p5:
            raise ValueError(f"P5 run identity is missing fields: {', '.join(missing_p5)}")
        normalized.update({field: identity[field] for field in _P5_IDENTITY_FIELDS})
    for field in (
        "dataset_sha256",
        "knowledge_manifest_sha256",
        "experiment_plan_sha256",
    ):
        value = normalized[field]
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ValueError(f"M5D run identity has invalid {field}")
    for field in ("pre_experiment_sha", "evaluated_git_sha"):
        value = normalized[field]
        if not isinstance(value, str) or _SHA1.fullmatch(value) is None:
            raise ValueError(f"M5D run identity has invalid {field}")
    if "evaluation_harness_sha" in normalized:
        value = normalized["evaluation_harness_sha"]
        if not isinstance(value, str) or _SHA1.fullmatch(value) is None:
            raise ValueError("M5D run identity has invalid evaluation_harness_sha")
    if is_p4:
        for field in (
            "scorer_manifest_sha256",
            "scorer_fixture_sha256",
            "scorer_spec_sha256",
            "scorer_implementation_sha256",
            "p4_schema_sha256",
        ):
            value = normalized[field]
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError(f"P4 run identity has invalid {field}")
        for field in (
            "application_under_test_sha",
            "freeze_commit_sha",
            "hosted_ci_head_sha",
            "scorer_definition_commit_sha",
        ):
            value = normalized[field]
            if not isinstance(value, str) or _SHA1.fullmatch(value) is None:
                raise ValueError(f"P4 run identity has invalid {field}")
        ci_run_id = normalized["hosted_ci_run_id"]
        if isinstance(ci_run_id, bool) or not isinstance(ci_run_id, int) or ci_run_id <= 0:
            raise ValueError("P4 run identity has invalid hosted_ci_run_id")
        if not isinstance(normalized.get("scorer_version"), str):
            raise ValueError("P4 run identity has invalid scorer_version")
        if not isinstance(normalized.get("grounding_finalizer_version"), str):
            raise ValueError("P4 run identity has invalid grounding_finalizer_version")
        if (
            not isinstance(normalized.get("evaluation_harness_sha"), str)
            or _SHA1.fullmatch(normalized["evaluation_harness_sha"]) is None
        ):
            raise ValueError("P4 run identity has invalid evaluation_harness_sha")
        if not (
            normalized["application_under_test_sha"]
            == normalized["evaluated_git_sha"]
            == normalized["freeze_commit_sha"]
            == normalized["hosted_ci_head_sha"]
        ):
            raise ValueError("P4 application, evaluated, freeze, and hosted CI SHAs must match")
        if (
            normalized["benchmark_version"] != "rag-v0.2"
            or normalized["split"] != "dev"
            or normalized["evidence_gate"] != "G2_TOP_EVIDENCE_CROSS_ENCODER"
            or normalized["evidence_gate_threshold"] != 0.2554669
            or normalized["model_candidate"] != "M0"
            or normalized["model_revision"] != "groq/openai/gpt-oss-120b"
            or normalized["retrieval_profile_version"] != "knowledge-retrieval-v1.1"
            or normalized["agent_prompt_version"] != "text-agent-system-p4-evidence-linked-v1"
            or normalized["agent_graph_version"] != "text-agent-m5d-v1"
            or normalized["grounding_finalizer_version"]
            != "evidence-linked-extractive-single-pass-v1"
            or normalized["scorer_version"] != "rag-v0.2-scorer-v2"
        ):
            raise ValueError("P4 run identity differs from its frozen candidate contract")
    if is_p5:
        if (
            re.fullmatch(r"canonical-M0-P5-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}", normalized["run_id"])
            is None
        ):
            raise ValueError("P5 run identity has an invalid canonical run ID")
        for field in (
            "scorer_implementation_sha256",
            "scorer_manifest_sha256",
            "scorer_fixture_sha256",
            "scorer_spec_sha256",
            "local_output_schema_sha256",
            "agent_prompt_sha256",
            "hosted_ci_job_conclusions_sha256",
            "p5_experiment_plan_sha256",
        ):
            if (
                not isinstance(normalized[field], str)
                or _SHA256.fullmatch(normalized[field]) is None
            ):
                raise ValueError(f"P5 run identity has invalid {field}")
        for field in (
            "application_under_test_sha",
            "implementation_freeze_sha",
            "hosted_ci_head_sha",
            "scorer_definition_commit_sha",
        ):
            if not isinstance(normalized[field], str) or _SHA1.fullmatch(normalized[field]) is None:
                raise ValueError(f"P5 run identity has invalid {field}")
        ci_run_id = normalized["hosted_ci_run_id"]
        if isinstance(ci_run_id, bool) or not isinstance(ci_run_id, int) or ci_run_id <= 0:
            raise ValueError("P5 run identity has invalid hosted_ci_run_id")
        if normalized["hosted_ci_conclusion"] != "success":
            raise ValueError("P5 run identity requires successful hosted CI")
        if (
            normalized["evaluated_git_sha"] != normalized["application_under_test_sha"]
            or normalized["application_under_test_sha"] != normalized["implementation_freeze_sha"]
            or normalized["implementation_freeze_sha"] != normalized["hosted_ci_head_sha"]
        ):
            raise ValueError("P5 application, implementation freeze, and hosted CI SHAs must match")
        if (
            normalized["benchmark_version"] != "rag-v0.2"
            or normalized["split"] != "dev"
            or normalized["dataset_sha256"]
            != "398521c3a2974634c7d8aace8a391fac33b10b60c3718814d4b222612168a595"
            or normalized["knowledge_manifest_sha256"]
            != "26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660"
            or normalized["experiment_plan_sha256"] != normalized["p5_experiment_plan_sha256"]
            or normalized["evidence_gate"] != "G2_TOP_EVIDENCE_CROSS_ENCODER"
            or normalized["evidence_gate_threshold"] != 0.2554669
            or normalized["grounding_candidate"] != "P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS"
            or normalized["model_candidate"] != "M0"
            or normalized["model_revision"] != "groq/openai/gpt-oss-120b"
            or normalized["provider"] != "Groq"
            or normalized["capability_alias"] != "agent-fast"
            or normalized["retrieval_profile_version"] != "knowledge-retrieval-v1.1"
            or normalized["retrieval_strategy"] != "hybrid_rrf"
            or normalized["final_evidence_count"] != 5
            or normalized["agent_prompt_version"] != "text-agent-system-p4-evidence-linked-v1"
            or normalized["agent_graph_version"] != "text-agent-m5d-v1"
            or normalized["grounding_finalizer_version"]
            != "evidence-linked-extractive-single-pass-v1"
            or normalized["knowledge_terminal_output_transport"]
            != "prompt_json_plain_content_no_response_format"
            or normalized["tool_choice"] != "auto"
            or normalized["provider_response_format_attached"] is not False
            or normalized["scorer_version"] != "rag-v0.2-scorer-v2"
        ):
            raise ValueError("P5 run identity differs from its frozen candidate contract")
    threshold = normalized["evidence_gate_threshold"]
    if isinstance(threshold, str):
        if (
            normalized["evidence_gate"] != "CALIBRATE_ALL_PREREGISTERED_GATES"
            or threshold != "calibration_sweep"
        ):
            raise ValueError("M5D run identity has an invalid evidence-gate threshold")
    elif threshold is not None and (
        isinstance(threshold, bool)
        or not isinstance(threshold, int | float)
        or not math.isfinite(float(threshold))
    ):
        raise ValueError("M5D run identity has a non-finite evidence-gate threshold")
    if threshold is None:
        raise ValueError("M5D run identity requires an explicit threshold or calibration sweep")
    for field in (
        *_IDENTITY_FIELDS,
        *_OPTIONAL_IDENTITY_FIELDS,
        *_P4_IDENTITY_FIELDS,
        *_P5_IDENTITY_FIELDS,
    ):
        if field not in normalized:
            continue
        if field == "evidence_gate_threshold" and normalized[field] is None:
            continue
        value = normalized[field]
        if not isinstance(value, str | int | float | bool) or not str(value):
            raise ValueError(f"M5D run identity has an invalid {field}")
    return normalized


def run_identity_sha256(identity: Mapping[str, Any]) -> str:
    normalized = _validated_identity(identity)
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _identity_path(checkpoint_path: Path) -> Path:
    return checkpoint_path.with_name(f"{checkpoint_path.name}.identity.json")


def bind_checkpoint_identity(checkpoint_path: Path, identity: Mapping[str, Any]) -> str:
    """Create or validate the immutable identity sidecar for a JSONL checkpoint."""

    normalized = _validated_identity(identity)
    fingerprint = run_identity_sha256(normalized)
    sidecar = _identity_path(checkpoint_path)
    if sidecar.exists():
        try:
            stored = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("invalid M5D checkpoint identity sidecar") from error
        if (
            not isinstance(stored, dict)
            or stored.get("identity") != normalized
            or stored.get("run_identity_sha256") != fingerprint
        ):
            raise ValueError("M5D checkpoint identity mismatch")
        return fingerprint
    if checkpoint_path.exists() and checkpoint_path.stat().st_size:
        raise ValueError("M5D checkpoint has no bound run identity")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.touch(exist_ok=True)
    temporary = sidecar.with_suffix(f"{sidecar.suffix}.tmp")
    temporary.write_text(
        json.dumps(
            {"identity": normalized, "run_identity_sha256": fingerprint},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(sidecar)
    return fingerprint


def load_checkpoint_records(
    checkpoint_path: Path,
    identity: Mapping[str, Any],
    *,
    expected_case_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Load only records carrying the exact sidecar identity and unique expected IDs."""

    fingerprint = bind_checkpoint_identity(checkpoint_path, identity)
    records: dict[str, dict[str, Any]] = {}
    if not checkpoint_path.exists():
        return records
    for line_number, line in enumerate(checkpoint_path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("checkpoint record must be an object")
            case_id = record.get("case_id")
            if not isinstance(case_id, str) or case_id not in expected_case_ids:
                raise ValueError("checkpoint case ID is unknown")
            if case_id in records:
                raise ValueError(f"duplicate checkpoint case ID: {case_id}")
            if (
                record.get("run_id") != identity["run_id"]
                or record.get("run_identity_sha256") != fingerprint
            ):
                raise ValueError("checkpoint record run identity mismatch")
            records[case_id] = record
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid M5D checkpoint line {line_number}: {error}") from error
    return records


def require_committed_behavior(repo_root: Path, *, pre_experiment_sha: str | None = None) -> str:
    """Reject tracked edits and untracked files outside generated M5D output roots."""

    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    unexpected: list[str] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        status = line[:2]
        path = line[3:].replace("\\", "/")
        if status == "??":
            candidate = PurePosixPath(path)
            if any(candidate == root or root in candidate.parents for root in _GENERATED_ROOTS):
                continue
        unexpected.append(line)
    if unexpected:
        raise ValueError(
            "uncommitted behavior or specification changes prevent canonical execution: "
            + "; ".join(unexpected)
        )
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if pre_experiment_sha is not None:
        if _SHA1.fullmatch(pre_experiment_sha) is None:
            raise ValueError("PRE_EXPERIMENT_SHA must be a 40-character lowercase Git SHA")
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", pre_experiment_sha, git_sha],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if ancestor.returncode != 0:
            raise ValueError("evaluated code does not contain PRE_EXPERIMENT_SHA")
    return git_sha


def build_agent_evaluation_profile(
    grounding_candidate: str,
    *,
    evidence_gate: str,
    evidence_gate_threshold: float,
    model_candidate: str,
) -> AgentEvaluationProfile:
    """Construct the exact profile passed to the evaluation API runtime."""

    return AgentEvaluationProfile(
        grounding_candidate=GroundingCandidate(grounding_candidate),
        evidence_gate=EvidenceGate(evidence_gate),
        evidence_gate_threshold=evidence_gate_threshold,
        model_candidate=model_candidate,
    )


def build_p4_run_identity(
    repo_root: Path,
    *,
    profile: AgentEvaluationProfile,
    run_id: str,
    freeze_commit_sha: str,
    hosted_ci_run_id: int,
    hosted_ci_head_sha: str,
) -> dict[str, Any]:
    """Build the complete identity for the single frozen M5D-B2 P4 run."""

    if profile.grounding_candidate is not GroundingCandidate.P4_EVIDENCE_LINKED_SINGLE_PASS:
        raise ValueError("P4 identity requires the P4 evaluation profile")
    if (
        not isinstance(run_id, str)
        or not run_id.startswith("canonical-M0-P4-")
        or "/" in run_id
        or "\\" in run_id
    ):
        raise ValueError("P4 identity requires a canonical M0 P4 run ID")
    if not isinstance(freeze_commit_sha, str) or _SHA1.fullmatch(freeze_commit_sha) is None:
        raise ValueError("P4 identity requires a full freeze commit SHA")
    if hosted_ci_head_sha != freeze_commit_sha:
        raise ValueError("hosted CI head must equal the P4 freeze commit SHA")
    if (
        isinstance(hosted_ci_run_id, bool)
        or not isinstance(hosted_ci_run_id, int)
        or hosted_ci_run_id <= 0
    ):
        raise ValueError("P4 identity requires a positive hosted CI run ID")
    commit_exists = subprocess.run(
        ["git", "cat-file", "-e", f"{freeze_commit_sha}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if commit_exists.returncode != 0:
        raise ValueError("P4 freeze commit SHA is not present in the repository")

    from verbaops.evaluation.m5d_b2_preregistration import (
        PLAN_PATH,
        audit_m5d_b2_preregistration,
    )

    audit_m5d_b2_preregistration(repo_root)
    plan_path = repo_root / PLAN_PATH
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    scorer_manifest_path = repo_root / "evals/rag/v0.2/scorer-v2/manifest.json"
    scorer_manifest = json.loads(scorer_manifest_path.read_text(encoding="utf-8"))
    schema_path = repo_root / plan["candidate"]["schema_path"]
    dataset_path = repo_root / "evals/rag/v0.2/questions.jsonl"
    knowledge_manifest_path = repo_root / "knowledge/novacommerce/manifest.json"
    harness_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if _SHA1.fullmatch(harness_sha) is None:
        raise ValueError("P4 evaluation harness SHA is invalid")
    model = plan["frozen_environment"]["model"]
    if (
        profile.evidence_gate is None
        or profile.evidence_gate.value != plan["frozen_environment"]["evidence_gate"]
        or profile.evidence_gate_threshold != plan["frozen_environment"]["evidence_gate_threshold"]
        or profile.model_candidate != plan["frozen_environment"]["model_candidate"]
        or profile.grounding_finalizer_version != plan["candidate"]["grounding_finalizer_version"]
    ):
        raise ValueError("P4 profile differs from the frozen gate, model, or finalizer contract")

    identity = {
        "benchmark_version": plan["benchmark_version"],
        "split": plan["execution"]["split"],
        "dataset_sha256": plan["dataset_sha256"],
        "knowledge_manifest_sha256": scorer_manifest["knowledge_manifest_sha256"],
        "experiment_plan_sha256": _sha256_path(plan_path),
        "pre_experiment_sha": plan["frozen_environment"]["pre_experiment_sha"],
        "evaluated_git_sha": freeze_commit_sha,
        "evaluation_harness_sha": harness_sha,
        "evidence_gate": profile.evidence_gate.value,
        "evidence_gate_threshold": profile.evidence_gate_threshold,
        "grounding_candidate": profile.grounding_candidate.value,
        "model_candidate": profile.model_candidate,
        "retrieval_profile_version": plan["frozen_environment"]["retrieval_profile_version"],
        "agent_prompt_version": f"text-agent-system-{profile.prompt_version}",
        "agent_graph_version": profile.graph_version,
        "model_revision": model,
        "run_id": run_id,
        "scorer_version": scorer_manifest["scorer_version"],
        "scorer_manifest_sha256": _sha256_path(scorer_manifest_path),
        "scorer_fixture_sha256": scorer_manifest["fixture_data_sha256"],
        "scorer_spec_sha256": scorer_manifest["scorer_spec_sha256"],
        "scorer_implementation_sha256": scorer_manifest["scorer_implementation_sha256"],
        "scorer_definition_commit_sha": scorer_manifest["scorer_frozen_at_commit_sha"],
        "p4_schema_sha256": _sha256_path(schema_path),
        "application_under_test_sha": freeze_commit_sha,
        "freeze_commit_sha": freeze_commit_sha,
        "hosted_ci_run_id": hosted_ci_run_id,
        "hosted_ci_head_sha": hosted_ci_head_sha,
        "grounding_finalizer_version": profile.grounding_finalizer_version,
    }
    # These bytes are hashed into the identity. Compare them to the values that
    # the frozen plan and knowledge manifest commit, rather than trusting a
    # potentially edited manifest value.
    if _sha256_path(dataset_path) != identity["dataset_sha256"]:
        raise ValueError("P4 dataset SHA256 differs from the frozen experiment plan")
    if _sha256_path(knowledge_manifest_path) != identity["knowledge_manifest_sha256"]:
        raise ValueError("P4 knowledge manifest SHA256 differs from the frozen contract")
    required = set(plan["run_identity"]["required_fields"])
    missing = sorted(required - identity.keys())
    if missing:
        raise ValueError(f"P4 identity is missing frozen fields: {', '.join(missing)}")
    return _validated_identity(identity)


def build_p5_run_identity(
    repo_root: Path,
    *,
    profile: AgentEvaluationProfile,
    run_id: str,
    freeze_commit_sha: str,
    hosted_ci_run_id: int,
    hosted_ci_head_sha: str,
    hosted_ci_conclusion: str,
    job_conclusions: Mapping[str, str],
) -> dict[str, Any]:
    """Build the complete identity for the single frozen M5D-B2 P5 DEV run."""

    from verbaops.evaluation.m5d_b2_p5_preregistration import (
        P5_PLAN_PATH,
        P5_PLAN_SHA256,
        REQUIRED_P5_HOSTED_CI_JOBS,
        audit_m5d_b2_p5_preregistration,
    )

    if profile.grounding_candidate is not GroundingCandidate.P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS:
        raise ValueError("P5 identity requires the P5 evaluation profile")
    if (
        not isinstance(run_id, str)
        or re.fullmatch(r"canonical-M0-P5-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}", run_id) is None
    ):
        raise ValueError("P5 identity requires a canonical M0 P5 run ID")
    if not isinstance(freeze_commit_sha, str) or _SHA1.fullmatch(freeze_commit_sha) is None:
        raise ValueError("P5 identity requires a full implementation freeze SHA")
    if hosted_ci_head_sha != freeze_commit_sha:
        raise ValueError("hosted CI head must equal the P5 implementation freeze SHA")
    if hosted_ci_conclusion != "success":
        raise ValueError("P5 identity requires successful hosted CI")
    if (
        isinstance(hosted_ci_run_id, bool)
        or not isinstance(hosted_ci_run_id, int)
        or hosted_ci_run_id <= 0
    ):
        raise ValueError("P5 identity requires a positive hosted CI run ID")
    if set(job_conclusions) != set(REQUIRED_P5_HOSTED_CI_JOBS) or any(
        job_conclusions[name] != "success" for name in REQUIRED_P5_HOSTED_CI_JOBS
    ):
        raise ValueError("P5 identity requires all 16 exact hosted CI jobs to succeed")
    commit_exists = subprocess.run(
        ["git", "cat-file", "-e", f"{freeze_commit_sha}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if commit_exists.returncode != 0:
        raise ValueError("P5 implementation freeze SHA is not present in the repository")

    audit_m5d_b2_p5_preregistration(repo_root)
    plan_path = repo_root / P5_PLAN_PATH
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    environment = plan["frozen_environment"]
    candidate = plan["candidate"]
    scorer = plan["scorer_contract"]
    schema_path = repo_root / plan["local_output_contract"]["schema_path"]
    prompt_path = repo_root / candidate["agent_prompt_path"]
    dataset_path = repo_root / "evals/rag/v0.2/questions.jsonl"
    knowledge_manifest_path = repo_root / "knowledge/novacommerce/manifest.json"
    if _sha256_path(plan_path) != P5_PLAN_SHA256:
        raise ValueError("P5 experiment plan bytes differ from the frozen plan")
    if (
        profile.evidence_gate is None
        or profile.evidence_gate.value != environment["evidence_gate"]
        or profile.evidence_gate_threshold != environment["evidence_gate_threshold"]
        or profile.model_candidate != environment["model_candidate"]
        or profile.prompt_version != "p4-evidence-linked-v1"
        or profile.graph_version != candidate["agent_graph_version"]
        or profile.grounding_finalizer_version != candidate["grounding_finalizer_version"]
    ):
        raise ValueError("P5 profile differs from the frozen candidate contract")
    harness_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if harness_sha != freeze_commit_sha:
        raise ValueError("P5 inference requires harness HEAD to equal the implementation freeze")

    manifest = json.loads((repo_root / plan["scorer_contract"]["manifest_path"]).read_text())
    jobs_payload = json.dumps(job_conclusions, sort_keys=True, separators=(",", ":"))
    jobs_sha256 = hashlib.sha256(jobs_payload.encode("utf-8")).hexdigest()
    p5_plan_sha256 = _sha256_path(plan_path)
    identity = {
        "benchmark_version": plan["benchmark_version"],
        "split": plan["execution"]["split"],
        "dataset_sha256": environment["dataset_sha256"],
        "knowledge_manifest_sha256": environment["knowledge_manifest_sha256"],
        "experiment_plan_sha256": p5_plan_sha256,
        "pre_experiment_sha": PRE_EXPERIMENT_SHA,
        "evaluated_git_sha": freeze_commit_sha,
        "evaluation_harness_sha": harness_sha,
        "evidence_gate": profile.evidence_gate.value,
        "evidence_gate_threshold": profile.evidence_gate_threshold,
        "grounding_candidate": profile.grounding_candidate.value,
        "model_candidate": profile.model_candidate,
        "retrieval_profile_version": environment["retrieval_profile_version"],
        "agent_prompt_version": candidate["agent_prompt_version"],
        "agent_graph_version": profile.graph_version,
        "model_revision": environment["model_revision"],
        "run_id": run_id,
        "p5_experiment_plan_sha256": p5_plan_sha256,
        "scorer_version": scorer["version"],
        "scorer_definition_commit_sha": scorer["definition_commit_sha"],
        "scorer_implementation_sha256": scorer["implementation_sha256"],
        "scorer_manifest_sha256": scorer["manifest_sha256"],
        "scorer_fixture_sha256": scorer["fixture_sha256"],
        "scorer_spec_sha256": scorer["spec_sha256"],
        "local_output_schema_sha256": _sha256_path(schema_path),
        "application_under_test_sha": freeze_commit_sha,
        "implementation_freeze_sha": freeze_commit_sha,
        "hosted_ci_run_id": hosted_ci_run_id,
        "hosted_ci_head_sha": hosted_ci_head_sha,
        "hosted_ci_conclusion": hosted_ci_conclusion,
        "hosted_ci_job_conclusions_sha256": jobs_sha256,
        "provider": environment["provider"],
        "capability_alias": environment["capability_alias"],
        "retrieval_strategy": environment["retrieval_strategy"],
        "final_evidence_count": environment["final_evidence_count"],
        "agent_prompt_sha256": _sha256_path(prompt_path),
        "grounding_finalizer_version": profile.grounding_finalizer_version,
        "knowledge_terminal_output_transport": plan["knowledge_terminal_output_transport"],
        "tool_choice": plan["knowledge_request"]["tool_choice"],
        "provider_response_format_attached": plan["knowledge_request"][
            "provider_response_format_attached"
        ],
    }
    if (
        _sha256_path(dataset_path) != identity["dataset_sha256"]
        or _sha256_path(knowledge_manifest_path) != identity["knowledge_manifest_sha256"]
    ):
        raise ValueError("P5 dataset or knowledge manifest differs from the frozen plan")
    required = set(plan["run_identity"]["required_fields"])
    missing = sorted(required - identity.keys())
    if missing:
        raise ValueError(f"P5 identity is missing frozen fields: {', '.join(missing)}")
    if scorer["definition_commit_sha"] != manifest["scorer_frozen_at_commit_sha"]:
        raise ValueError("P5 scorer definition commit differs from the frozen manifest")
    return _validated_identity(identity)


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_canonical_revisions(
    repo_root: Path,
    *,
    application_sha: str = CANONICAL_APPLICATION_SHA,
    pre_experiment_sha: str | None = PRE_EXPERIMENT_SHA,
) -> tuple[str, str]:
    """Return the immutable app SHA and evaluation-harness revision separately.

    Only committed changes confined to evaluation/provenance and explicitly
    permitted evidence/report paths may follow the canonical application SHA.
    Generated evidence outputs may be untracked while a run is in progress.
    """

    if not isinstance(application_sha, str) or _SHA1.fullmatch(application_sha) is None:
        raise ValueError("canonical application SHA must be a 40-character Git SHA")
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    unexpected: list[str] = []
    for line in status.splitlines():
        if not line:
            continue
        path = line[3:].replace("\\", "/").split(" -> ")[-1]
        candidate = PurePosixPath(path)
        if candidate != _CANONICAL_OUTPUT_ROOT and _CANONICAL_OUTPUT_ROOT not in candidate.parents:
            unexpected.append(line)
    if unexpected:
        raise ValueError(
            "uncommitted behavior or specification changes prevent canonical execution: "
            + "; ".join(unexpected)
        )
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if pre_experiment_sha is not None:
        if _SHA1.fullmatch(pre_experiment_sha) is None:
            raise ValueError("PRE_EXPERIMENT_SHA must be a 40-character lowercase Git SHA")
        preregistration = subprocess.run(
            ["git", "merge-base", "--is-ancestor", pre_experiment_sha, head_sha],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if preregistration.returncode != 0:
            raise ValueError("evaluation harness does not contain PRE_EXPERIMENT_SHA")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", application_sha, head_sha],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0:
        raise ValueError("canonical application SHA is not an ancestor of the harness revision")
    changed = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", application_sha, head_sha],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    disallowed = [
        path.replace("\\", "/")
        for path in changed
        if path.replace("\\", "/") not in _APPROVED_HARNESS_PATHS
        and not any(
            path.replace("\\", "/").startswith(prefix) for prefix in _APPROVED_HARNESS_PREFIXES
        )
    ]
    if disallowed:
        raise ValueError(
            "application behavior drift since the canonical application SHA: "
            + ", ".join(disallowed)
        )
    harness_history = subprocess.run(
        ["git", "log", "-1", "--format=%H", head_sha, "--", *_HARNESS_REVISION_PATHS],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if _SHA1.fullmatch(harness_history) is None:
        raise ValueError("evaluation harness revision could not be resolved")
    return application_sha, harness_history


def _canonical_json_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def migrate_checkpoint_provenance(
    checkpoint_path: Path,
    *,
    corrected_identity: Mapping[str, Any],
    expected_case_queries: Mapping[str, str],
    runtime_traces: Sequence[Mapping[str, Any]],
    correction_artifact_path: Path,
    harness_correction_sha: str,
    apply_canonical_provenance_correction: bool = False,
    dry_run_canonical_provenance_correction: bool = False,
) -> dict[str, Any]:
    """One-time, trace-proven correction for the known M5D identity drift.

    This deliberately does not alter bind_checkpoint_identity(): normal resume
    continues to reject any sidecar mismatch.
    """

    if not apply_canonical_provenance_correction and not dry_run_canonical_provenance_correction:
        raise ValueError("explicit canonical provenance correction apply flag is required")
    if _SHA1.fullmatch(harness_correction_sha) is None:
        raise ValueError("harness correction SHA is invalid")
    if corrected_identity.get("evaluation_harness_sha") != harness_correction_sha:
        raise ValueError("corrected identity does not bind the harness correction SHA")
    if correction_artifact_path.exists():
        raise ValueError("canonical provenance correction artifact already exists")
    sidecar_path = _identity_path(checkpoint_path)
    if not checkpoint_path.is_file() or not sidecar_path.is_file():
        raise ValueError("checkpoint or immutable identity sidecar is missing")
    try:
        old_sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("checkpoint identity sidecar is invalid") from error
    if not isinstance(old_sidecar, dict) or not isinstance(old_sidecar.get("identity"), dict):
        raise ValueError("checkpoint identity sidecar is invalid")
    old_identity = old_sidecar["identity"]
    if "evaluation_harness_sha" in old_identity:
        raise ValueError("checkpoint already carries an evaluation harness identity")
    old_identity_sha = run_identity_sha256(old_identity)
    if old_sidecar.get("run_identity_sha256") != old_identity_sha:
        raise ValueError("checkpoint identity sidecar fingerprint is corrupt")
    normalized_corrected = _validated_identity(corrected_identity)
    if normalized_corrected.get("run_id") != old_identity.get("run_id"):
        raise ValueError("provenance correction cannot change run ID")
    if normalized_corrected.get("evaluated_git_sha") != CANONICAL_APPLICATION_SHA:
        raise ValueError("provenance correction is not bound to the canonical application SHA")
    run_id = old_identity.get("run_id")
    migration = _MIGRATABLE_RUNS.get(str(run_id))
    if migration is None:
        raise ValueError("run is not an explicitly migratable canonical candidate")
    expected_candidate, expected_old_sha, old_prompt = migration
    if old_identity_sha != expected_old_sha:
        raise ValueError(
            "historical identity fingerprint differs from the reviewed migration target"
        )
    if old_identity.get("grounding_candidate") != expected_candidate:
        raise ValueError("historical candidate differs from the reviewed migration target")
    if old_identity.get("agent_graph_version") != "text-agent-v2":
        raise ValueError("historical identity does not match the known graph-version defect")
    if old_identity.get("agent_prompt_version") != old_prompt:
        raise ValueError("historical prompt version differs from the known runner defect")
    expected_prompt = {
        "P0_CURRENT": "text-agent-system-v2",
        "P1_PROMPT_V3": "text-agent-system-v3",
        "P2_FAIL_CLOSED_CITATIONS": "text-agent-system-v3",
    }[expected_candidate]
    if normalized_corrected.get("agent_prompt_version") != expected_prompt:
        raise ValueError("corrected prompt version does not match the runtime profile")
    if normalized_corrected.get("agent_graph_version") != "text-agent-m5d-v1":
        raise ValueError("corrected graph version does not match the runtime profile")
    allowed_identity_changes = {
        "agent_prompt_version",
        "agent_graph_version",
        "evaluation_harness_sha",
    }
    if any(
        old_identity.get(key) != normalized_corrected.get(key)
        for key in old_identity
        if key not in allowed_identity_changes
    ) or any(
        key not in old_identity and key not in allowed_identity_changes
        for key in normalized_corrected
    ):
        raise ValueError("provenance correction changes fields outside the known identity defect")
    expected_case_ids = set(expected_case_queries)
    if not expected_case_ids or any(
        not isinstance(query, str) for query in expected_case_queries.values()
    ):
        raise ValueError("expected case query mapping is invalid")
    records = load_checkpoint_records(
        checkpoint_path,
        old_identity,
        expected_case_ids=expected_case_ids,
    )
    if not records:
        raise ValueError("checkpoint contains no completed observations")
    trace_by_case: dict[str, Mapping[str, Any]] = {}
    for trace in runtime_traces:
        case_id = trace.get("case_id")
        if not isinstance(case_id, str) or case_id in trace_by_case:
            raise ValueError("runtime trace case association is missing or duplicated")
        trace_by_case[case_id] = trace
    if set(trace_by_case) != set(records):
        raise ValueError("runtime trace count does not match checkpoint observations")
    trace_run_ids = [str(trace.get("agent_run_id", "")) for trace in trace_by_case.values()]
    if any(not run_id for run_id in trace_run_ids) or len(set(trace_run_ids)) != len(trace_run_ids):
        raise ValueError("runtime trace agent run IDs are missing or duplicated")
    trace_evidence: list[dict[str, str]] = []
    for case_id, record in records.items():
        trace = trace_by_case[case_id]
        if (
            trace.get("agent_run_id") != record.get("agent_run_id")
            or record.get("status") != "completed"
            or trace.get("status") != "completed"
            or trace.get("prompt_version") != normalized_corrected["agent_prompt_version"]
            or trace.get("graph_version") != normalized_corrected["agent_graph_version"]
            or trace.get("user_message") != expected_case_queries[case_id]
        ):
            raise ValueError(f"runtime trace does not prove corrected versions for {case_id}")
        if record.get("evaluated_git_sha") != CANONICAL_APPLICATION_SHA:
            raise ValueError(f"checkpoint observation has a mismatched application SHA: {case_id}")
        trace_application_sha = trace.get("application_under_test_sha")
        if trace_application_sha is not None and trace_application_sha != CANONICAL_APPLICATION_SHA:
            raise ValueError(f"runtime trace has a mismatched application SHA: {case_id}")
        trace_evidence.append(
            {
                "case_id": case_id,
                "agent_run_id": str(trace["agent_run_id"]),
                "prompt_version": str(trace["prompt_version"]),
                "graph_version": str(trace["graph_version"]),
                "status": str(trace["status"]),
                "user_message_sha256": hashlib.sha256(
                    str(trace["user_message"]).encode("utf-8")
                ).hexdigest(),
            }
        )

    corrected_identity_sha = run_identity_sha256(normalized_corrected)
    original_checkpoint_bytes = checkpoint_path.read_bytes()
    original_sidecar_bytes = sidecar_path.read_bytes()
    raw_records = [
        json.loads(line) for line in original_checkpoint_bytes.decode("utf-8").splitlines()
    ]
    before_non_provenance = [
        {key: value for key, value in record.items() if key != "run_identity_sha256"}
        for record in raw_records
    ]
    migrated_records = [
        {**record, "run_identity_sha256": corrected_identity_sha} for record in raw_records
    ]
    after_non_provenance = [
        {key: value for key, value in record.items() if key != "run_identity_sha256"}
        for record in migrated_records
    ]
    before_content_sha = _canonical_json_digest(before_non_provenance)
    after_content_sha = _canonical_json_digest(after_non_provenance)
    if before_content_sha != after_content_sha:
        raise ValueError("provenance migration would alter substantive observation content")
    corrected_checkpoint_bytes = "".join(
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        for record in migrated_records
    ).encode("utf-8")
    corrected_sidecar = {
        "identity": normalized_corrected,
        "run_identity_sha256": corrected_identity_sha,
    }
    corrected_sidecar_bytes = (
        json.dumps(corrected_sidecar, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    result = {
        "run_id": str(old_identity["run_id"]),
        "old_identity": old_identity,
        "old_identity_sha256": old_identity_sha,
        "corrected_identity": normalized_corrected,
        "corrected_identity_sha256": corrected_identity_sha,
        "changed_fields": [
            *[
                f"{field} (identity sidecar)"
                for field in ("agent_prompt_version", "agent_graph_version")
                if old_identity.get(field) != normalized_corrected.get(field)
            ],
            "evaluation_harness_sha (identity sidecar)",
            "run_identity_sha256 (checkpoint records)",
            "run_identity_sha256 (identity sidecar)",
            "run_identity (metadata.json)",
            "run_identity_sha256 (metadata.json)",
            "evaluation_harness_sha (metadata.json)",
            "run_identity (run-summary.json)",
            "run_identity_sha256 (run-summary.json)",
            "evaluation_harness_sha (run-summary.json)",
            *(
                ["canonical_run_identity_sha256 (report.json)"]
                if checkpoint_path.with_name("report.json").is_file()
                else []
            ),
        ],
        "reason": "Corrected duplicated evaluation-harness version logic to match persisted AgentEvaluationProfile traces.",
        "application_under_test_sha": CANONICAL_APPLICATION_SHA,
        "harness_correction_sha": harness_correction_sha,
        "verified_trace_count": len(trace_evidence),
        "trace_evidence": trace_evidence,
        "expected_prompt_version": normalized_corrected["agent_prompt_version"],
        "expected_graph_version": normalized_corrected["agent_graph_version"],
        "observed_prompt_versions": sorted({item["prompt_version"] for item in trace_evidence}),
        "observed_graph_versions": sorted({item["graph_version"] for item in trace_evidence}),
        "old_checkpoint_sha256": hashlib.sha256(original_checkpoint_bytes).hexdigest(),
        "corrected_checkpoint_sha256": hashlib.sha256(corrected_checkpoint_bytes).hexdigest(),
        "old_identity_sidecar_sha256": hashlib.sha256(original_sidecar_bytes).hexdigest(),
        "corrected_identity_sidecar_sha256": hashlib.sha256(corrected_sidecar_bytes).hexdigest(),
        "non_provenance_observation_sha256_before": before_content_sha,
        "non_provenance_observation_sha256_after": after_content_sha,
    }
    if dry_run_canonical_provenance_correction:
        return result
    correction_artifact_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_temp = checkpoint_path.with_name(checkpoint_path.name + ".provenance.tmp")
    sidecar_temp = sidecar_path.with_name(sidecar_path.name + ".provenance.tmp")
    artifact_bytes = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
    artifact_temp = correction_artifact_path.with_name(correction_artifact_path.name + ".tmp")
    try:
        checkpoint_temp.write_bytes(corrected_checkpoint_bytes)
        sidecar_temp.write_bytes(corrected_sidecar_bytes)
        artifact_temp.write_bytes(artifact_bytes)
        checkpoint_temp.replace(checkpoint_path)
        sidecar_temp.replace(sidecar_path)
        artifact_temp.replace(correction_artifact_path)
    except Exception:
        checkpoint_path.write_bytes(original_checkpoint_bytes)
        sidecar_path.write_bytes(original_sidecar_bytes)
        for temporary in (checkpoint_temp, sidecar_temp, artifact_temp):
            temporary.unlink(missing_ok=True)
        raise
    return result


def require_canonical_run_directory(repo_root: Path, run_dir: Path, *, run_id: str) -> Path:
    """Require a fresh run namespace below the canonical evidence root."""

    if run_dir.is_symlink():
        raise ValueError("canonical M5D run directory may not be a symlink")
    canonical_root = (repo_root / "evals/rag/v0.2/dev-evidence/canonical").resolve()
    resolved_run_dir = run_dir.resolve()
    if not resolved_run_dir.is_relative_to(canonical_root):
        raise ValueError("canonical M5D run directory must be under dev-evidence/canonical")
    if not run_id or resolved_run_dir.name != run_id:
        raise ValueError("canonical M5D run directory must match run ID")
    return resolved_run_dir


def artifact_reference(repo_root: Path, artifact_path: Path) -> dict[str, str]:
    resolved_root = repo_root.resolve()
    resolved_artifact = artifact_path.resolve()
    try:
        relative = resolved_artifact.relative_to(resolved_root).as_posix()
    except ValueError as error:
        raise ValueError("M5D artifact must be inside the repository") from error
    digest = hashlib.sha256(resolved_artifact.read_bytes()).hexdigest()
    return {"path": relative, "sha256": digest}


def verify_artifact_references(repo_root: Path, references: Sequence[Any]) -> None:
    """Verify relative, repository-confined artifact references before dependent runs."""

    resolved_root = repo_root.resolve()
    if not references:
        raise ValueError("M5D artifact references are required")
    for reference in references:
        if not isinstance(reference, dict):
            raise ValueError("M5D artifact reference is invalid")
        relative = reference.get("path")
        digest = reference.get("sha256")
        path = PurePosixPath(relative) if isinstance(relative, str) else None
        if (
            path is None
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in str(relative)
            or ":" in str(relative)
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
        ):
            raise ValueError("M5D artifact path or sha256 is invalid")
        resolved = (resolved_root / Path(*path.parts)).resolve()
        try:
            resolved.relative_to(resolved_root)
        except ValueError as error:
            raise ValueError("M5D artifact path escapes repository root") from error
        try:
            actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
        except OSError as error:
            raise ValueError("M5D artifact referenced by run provenance is missing") from error
        if actual != digest:
            raise ValueError("M5D artifact sha256 does not match run provenance")


def validate_dev_decision_provenance(decision: Mapping[str, Any]) -> None:
    """Fail closed when a decision claims canonical completion without bound artifacts."""

    status = decision.get("canonical_evidence_status")
    runs = decision.get("canonical_runs")
    evaluated_shas = decision.get("evaluated_git_shas")
    if status == "COMPLETE" and (
        not isinstance(decision.get("pre_experiment_sha"), str)
        or not isinstance(evaluated_shas, list)
        or not evaluated_shas
        or not isinstance(runs, list)
        or not runs
    ):
        raise ValueError("canonical provenance is required for a complete DEV decision")
    if status not in ("COMPLETE", "PARTIAL") and runs is None:
        return
    if status in ("COMPLETE", "PARTIAL"):
        pre_experiment_sha = decision.get("pre_experiment_sha")
        if not isinstance(pre_experiment_sha, str) or _SHA1.fullmatch(pre_experiment_sha) is None:
            raise ValueError("canonical provenance has invalid PRE_EXPERIMENT_SHA")
        if not isinstance(evaluated_shas, list) or any(
            not isinstance(value, str) or _SHA1.fullmatch(value) is None for value in evaluated_shas
        ):
            raise ValueError("canonical provenance has invalid evaluated Git SHAs")
        if not isinstance(runs, list):
            raise ValueError("canonical provenance must include run records")
        seen: set[str] = set()
        for run in runs:
            if not isinstance(run, dict):
                raise ValueError("canonical provenance run record is invalid")
            run_id = run.get("run_id")
            evaluated_sha = run.get("evaluated_git_sha")
            identity_sha = run.get("run_identity_sha256")
            artifacts = run.get("artifacts")
            if not isinstance(run_id, str) or not run_id or run_id in seen:
                raise ValueError("canonical provenance run ID is missing or duplicated")
            seen.add(run_id)
            if (
                not isinstance(evaluated_sha, str)
                or _SHA1.fullmatch(evaluated_sha) is None
                or evaluated_sha not in evaluated_shas
            ):
                raise ValueError("canonical provenance evaluated Git SHA is missing")
            if not isinstance(identity_sha, str) or _SHA256.fullmatch(identity_sha) is None:
                raise ValueError("canonical provenance run identity sha256 is missing")
            if run.get("run_type") == "GROUNDING_CANDIDATE":
                harness_sha = run.get("evaluation_harness_sha")
                if not isinstance(harness_sha, str) or _SHA1.fullmatch(harness_sha) is None:
                    raise ValueError("canonical grounding run harness SHA is missing or invalid")
            if not isinstance(artifacts, list) or not artifacts:
                raise ValueError("canonical provenance artifacts are required")
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    raise ValueError("canonical provenance artifact reference is invalid")
                path = artifact.get("path")
                digest = artifact.get("sha256")
                parsed = PurePosixPath(path) if isinstance(path, str) else None
                if (
                    parsed is None
                    or parsed.is_absolute()
                    or ".." in parsed.parts
                    or "\\" in str(path)
                    or ":" in str(path)
                    or not isinstance(digest, str)
                    or _SHA256.fullmatch(digest) is None
                ):
                    raise ValueError("canonical provenance artifact path or sha256 is invalid")


__all__ = [
    "CANONICAL_APPLICATION_SHA",
    "PRE_EXPERIMENT_SHA",
    "artifact_reference",
    "bind_checkpoint_identity",
    "build_agent_evaluation_profile",
    "build_p4_run_identity",
    "load_checkpoint_records",
    "migrate_checkpoint_provenance",
    "require_canonical_revisions",
    "require_canonical_run_directory",
    "require_committed_behavior",
    "run_identity_sha256",
    "validate_dev_decision_provenance",
    "verify_artifact_references",
]
