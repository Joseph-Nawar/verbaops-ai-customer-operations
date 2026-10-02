"""Frozen P5 plan audit and fail-closed authorization for its one canonical DEV run."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from verbaops.evaluation.m5d_b2_preregistration import (
    REQUIRED_HOSTED_CI_JOBS,
    audit_m5d_b2_p4_closeout,
)
from verbaops.evaluation.rag_v02_scorer_v2 import audit_scorer_v2

P5_PLAN_PATH = Path("evals/rag/v0.2/m5d-b2-p5-experiment-plan.json")
P5_PLAN_SHA256 = "e700ec31f157f47837489fc2d26e1296388405f447701286adc899d7b42fc20e"
P5_CANDIDATE_ID = "P5_PROMPT_JSON_EXTRACTIVE_SINGLE_PASS"
P5_RUN_ID = re.compile(r"canonical-M0-P5-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}\Z")
P5_CANONICAL_NAMESPACE = Path("evals/rag/v0.2/dev-evidence/canonical")
REQUIRED_P5_HOSTED_CI_JOBS = REQUIRED_HOSTED_CI_JOBS


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _p5_run_directories(root: Path) -> list[Path]:
    canonical_root = root / P5_CANONICAL_NAMESPACE
    if canonical_root.is_symlink():
        raise ValueError("P5 canonical run namespace contains a symlink")
    if not canonical_root.exists():
        return []
    return sorted(
        path
        for path in canonical_root.iterdir()
        if path.name.startswith("canonical-M0-P5-") and path.is_dir()
    )


def require_p5_canonical_run_directory(root: Path, run_directory: Path, *, run_id: str) -> Path:
    """Require a P5 directory directly below the one frozen canonical namespace."""

    if not isinstance(run_id, str) or P5_RUN_ID.fullmatch(run_id) is None:
        raise ValueError("canonical M0 P5 run ID is required")
    canonical_root = root / P5_CANONICAL_NAMESPACE
    path_components = [root]
    path_components.extend(
        root.joinpath(*P5_CANONICAL_NAMESPACE.parts[:index])
        for index in range(1, len(P5_CANONICAL_NAMESPACE.parts) + 1)
    )
    if any(path.is_symlink() for path in path_components) or run_directory.is_symlink():
        raise ValueError("canonical P5 namespace may not contain symlink paths")
    resolved_root = root.resolve()
    resolved_canonical_root = canonical_root.resolve()
    resolved_run_directory = run_directory.resolve()
    if not resolved_canonical_root.is_relative_to(resolved_root):
        raise ValueError("canonical P5 namespace escapes the repository")
    if resolved_run_directory != (resolved_canonical_root / run_id):
        raise ValueError("P5 run directory must be directly in the canonical P5 namespace")
    return resolved_run_directory


def audit_m5d_b2_p5_preregistration(root: Path) -> dict[str, Any]:
    """Check the immutable P5 plan, scorer-v2 contract, and closed P4 evidence."""

    plan_path = root / P5_PLAN_PATH
    if not plan_path.is_file() or _sha256(plan_path) != P5_PLAN_SHA256:
        raise ValueError("P5 experiment plan hash does not match the frozen preregistration")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    execution = plan.get("execution", {})
    environment = plan.get("frozen_environment", {})
    candidate = plan.get("candidate", {})
    request = plan.get("knowledge_request", {})
    transport = plan.get("knowledge_terminal_output_transport")
    if plan.get("candidate_ids") != [P5_CANDIDATE_ID]:
        raise ValueError("P5 plan must preregister exactly one P5 candidate")
    if execution.get("split") != "dev" or execution.get("case_count") != 96:
        raise ValueError("P5 plan must target exactly 96 DEV cases")
    if execution.get("release_holdout_access_allowed") is not False:
        raise ValueError("P5 plan must prohibit release holdout access")
    if execution.get("selection_artifact_allowed") is not False:
        raise ValueError("P5 plan must prohibit selection.json")
    if execution.get("canonical_p5_inference_enabled_in_this_pr") is not False:
        raise ValueError("P5 plan must remain preregistration-only before implementation")
    if execution.get("provider_inference_in_this_pr") is not False:
        raise ValueError("P5 plan must prohibit provider inference in implementation work")
    if (
        candidate.get("id") != P5_CANDIDATE_ID
        or candidate.get("status") != "preregistered_not_implemented"
    ):
        raise ValueError("P5 candidate plan status or ID changed")

    expected_environment = {
        "dataset_sha256": "398521c3a2974634c7d8aace8a391fac33b10b60c3718814d4b222612168a595",
        "knowledge_manifest_sha256": "26bf94fd2fea6b0b5ce0ba0c91f87ae67dad32b95446a9ae1fa8301e21ee4660",
        "retrieval_profile_version": "knowledge-retrieval-v1.1",
        "retrieval_strategy": "hybrid_rrf",
        "final_evidence_count": 5,
        "evidence_gate": "G2_TOP_EVIDENCE_CROSS_ENCODER",
        "evidence_gate_threshold": 0.2554669,
        "model_candidate": "M0",
        "model": "groq/openai/gpt-oss-120b",
        "capability_alias": "agent-fast",
    }
    if any(environment.get(field) != value for field, value in expected_environment.items()):
        raise ValueError("P5 frozen environment differs from its preregistration")
    if (
        transport != "prompt_json_plain_content_no_response_format"
        or request.get("tool_choice") != "auto"
        or request.get("existing_tools") is not True
        or request.get("provider_response_format_attached") is not False
        or request.get("response_format") is not None
    ):
        raise ValueError("P5 knowledge request transport differs from its preregistration")
    if candidate.get("agent_prompt_version") != "text-agent-system-p4-evidence-linked-v1":
        raise ValueError("P5 prompt version differs from the frozen P4 prompt")
    prompt_path = root / "src/verbaops/agent/prompts/system_p4_evidence_linked_v1.txt"
    if candidate.get("agent_prompt_sha256") != _sha256(prompt_path):
        raise ValueError("P5 prompt bytes differ from the frozen prompt")

    p4_closeout = audit_m5d_b2_p4_closeout(root)
    scorer = audit_scorer_v2(root)
    scorer_contract = plan.get("scorer_contract", {})
    manifest = scorer["manifest"]
    scorer_values = {
        "version": manifest["scorer_version"],
        "definition_commit_sha": manifest["scorer_frozen_at_commit_sha"],
        "implementation_sha256": manifest["scorer_implementation_sha256"],
        "manifest_sha256": _sha256(root / "evals/rag/v0.2/scorer-v2/manifest.json"),
        "fixture_sha256": manifest["fixture_data_sha256"],
        "spec_sha256": manifest["scorer_spec_sha256"],
    }
    if any(scorer_contract.get(field) != value for field, value in scorer_values.items()):
        raise ValueError("P5 scorer-v2 hashes differ from the committed scorer contract")
    schema_path = root / plan["local_output_contract"]["schema_path"]
    if plan["local_output_contract"].get("schema_sent_to_provider") is not False or plan[
        "local_output_contract"
    ].get("schema_sha256") != _sha256(schema_path):
        raise ValueError("P5 local output schema differs from the frozen contract")
    dataset_path = root / "evals/rag/v0.2/questions.jsonl"
    manifest_path = root / "knowledge/novacommerce/manifest.json"
    if _sha256(dataset_path) != environment["dataset_sha256"]:
        raise ValueError("P5 dataset hash differs from the frozen contract")
    if _sha256(manifest_path) != environment["knowledge_manifest_sha256"]:
        raise ValueError("P5 knowledge manifest hash differs from the frozen contract")
    if plan.get("quality_floors") != {
        "citation_precision_minimum": 0.95,
        "citation_precision_requires_nonzero_denominator": True,
        "labeled_groundedness_minimum": 0.9,
        "labeled_groundedness_requires_nonzero_denominator": True,
        "unsupported_recognized_fact_rate_maximum": 0.1,
        "expected_fact_coverage_minimum": 0.7,
        "zero_fabricated_or_non_supplied_evidence_handles": True,
        "trust_invariant_is_additional_to_quality_floors": True,
    }:
        raise ValueError("P5 quality floors differ from the frozen contract")
    selection_present = (root / "evals/rag/v0.2/selection.json").exists()
    if selection_present:
        raise ValueError("selection.json is prohibited during P5")

    return {
        "candidate_id": P5_CANDIDATE_ID,
        "split": "dev",
        "case_count": 96,
        "plan_sha256": P5_PLAN_SHA256,
        "p4_closeout_classification": p4_closeout["classification"],
        "release_holdout_access_allowed": False,
        "selection_artifact_allowed": False,
        "selection_json_present": False,
        "scorer_version": scorer_values["version"],
        "scorer_hashes": scorer_values,
        "schema_sha256": _sha256(schema_path),
        "dataset_sha256": _sha256(dataset_path),
        "knowledge_manifest_sha256": _sha256(manifest_path),
    }


def require_p5_inference_authorized(
    *,
    repo_root: Path,
    run_id: str,
    freeze_commit_sha: str | None,
    hosted_ci_run_id: int | None,
    hosted_ci_head_sha: str | None,
    hosted_ci_conclusion: str | None,
    job_conclusions: dict[str, str],
) -> None:
    """Authorize the one P5 namespace only on an exact committed green freeze."""

    if not isinstance(run_id, str) or P5_RUN_ID.fullmatch(run_id) is None:
        raise ValueError("canonical M0 P5 run ID is required")
    audit_m5d_b2_p5_preregistration(repo_root)
    directories = _p5_run_directories(repo_root)
    if any(path.is_symlink() for path in directories):
        raise ValueError("P5 canonical run namespace contains a symlink")
    if directories and [path.name for path in directories] != [run_id]:
        raise ValueError("P5 canonical run namespace contains an unrelated run")
    requested_directory = repo_root / P5_CANONICAL_NAMESPACE / run_id
    if (requested_directory / "report.json").exists():
        raise ValueError("completed canonical P5 run cannot resume")
    summary_path = requested_directory / "run-summary.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("P5 canonical run summary is malformed") from error
        completed_cases = summary.get("completed_cases") if isinstance(summary, dict) else None
        if (
            not isinstance(summary, dict)
            or summary.get("canonical") is not True
            or summary.get("run_id") != run_id
            or isinstance(completed_cases, bool)
            or not isinstance(completed_cases, int)
        ):
            raise ValueError("P5 canonical run summary identity is invalid")
        if completed_cases >= 96:
            raise ValueError("completed canonical P5 run cannot resume")
    if freeze_commit_sha is None or re.fullmatch(r"[a-f0-9]{40}", freeze_commit_sha) is None:
        raise ValueError("P5 requires a committed full implementation freeze SHA")
    if hosted_ci_head_sha != freeze_commit_sha:
        raise ValueError("P5 hosted CI must run on the exact implementation freeze SHA")
    if hosted_ci_conclusion != "success":
        raise ValueError("P5 requires successful hosted CI on the implementation freeze")
    if (
        isinstance(hosted_ci_run_id, bool)
        or not isinstance(hosted_ci_run_id, int)
        or hosted_ci_run_id <= 0
    ):
        raise ValueError("P5 hosted CI run ID must be a positive integer")
    if set(job_conclusions) != set(REQUIRED_P5_HOSTED_CI_JOBS):
        raise ValueError("P5 hosted CI must provide exactly the 16 required jobs")
    failed = [job for job in REQUIRED_P5_HOSTED_CI_JOBS if job_conclusions.get(job) != "success"]
    if failed:
        raise ValueError("P5 required jobs must all succeed: " + ", ".join(failed))

    from verbaops.evaluation.m5d_run_identity import (
        PRE_EXPERIMENT_SHA,
        require_committed_behavior,
    )

    current = require_committed_behavior(repo_root, pre_experiment_sha=PRE_EXPERIMENT_SHA)
    if current != freeze_commit_sha:
        raise ValueError("working-tree HEAD must equal the exact P5 implementation freeze")


__all__ = [
    "P5_CANDIDATE_ID",
    "P5_CANONICAL_NAMESPACE",
    "P5_PLAN_PATH",
    "P5_PLAN_SHA256",
    "REQUIRED_P5_HOSTED_CI_JOBS",
    "audit_m5d_b2_p5_preregistration",
    "require_p5_canonical_run_directory",
    "require_p5_inference_authorized",
]
