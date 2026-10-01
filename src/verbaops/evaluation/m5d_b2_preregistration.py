"""Provider-free M5D-B2 preregistration and future inference-unlock checks."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from verbaops.evaluation.rag_v02_scorer_v2 import audit_scorer_v2

PLAN_PATH = Path("evals/rag/v0.2/m5d-b2-experiment-plan.json")
P4_RUN_ID = "canonical-M0-P4-20261001T173102Z-31113cc8"
P4_RUN_IDENTITY_SHA256 = "4a041a8f5966715dce3461064f4e964f5efb55162c06e283128cb5ecb0031647"
P4_CLOSEOUT_CLASSIFICATION = (
    "P4_EXECUTION_INELIGIBLE_GROQ_RESPONSE_FORMAT_TOOL_CALLING_INCOMPATIBILITY"
)
P4_ARTIFACT_SHA256 = {
    "grounded_cases.jsonl": "0b650e8aecb34725f2a6786ee39aaab94530cd7f37f3dfa70da7343ca16a36f3",
    "grounded_cases.jsonl.identity.json": "bd2afde30e1e138664ee0d5e8fd652e5a7af1522f2f6655a3f351232dfa67d67",
    "interruption.json": "bdafb48e92d2b85e0dac20f0d3e498d22ba96d9b71b21a0dc8c71c9a3c7d3135",
    "metadata.json": "ea5990fda84930e5f01e249d50d7c0b77db4d066df57226dd343ced186056fd0",
    "run-summary.json": "2ce75645a87b982a48e004b6c649772bee48618c693859647ba24f56409cf5ff",
    "p4-traces/9f857402-47b7-4a96-b27e-1f6f81d698b1.json": (
        "35317a96470c4ed4f22d5aa6fc36f597720dfb1f5199865f1b9293329f23e00c"
    ),
}
REQUIRED_HOSTED_CI_JOBS = (
    "quality",
    "postgres-contract",
    "postgres-concurrency",
    "postgres-m3b",
    "postgres-m3d",
    "knowledge-contract",
    "rag-contract",
    "rag-evaluation-contract",
    "m5d-evaluation-contract",
    "commerce-acceptance",
    "llm-gateway-contract",
    "commerce-client-contract",
    "agent-acceptance",
    "web-quality",
    "evaluation-contract",
    "docker-build",
)
REQUIRED_P4_IDENTITY_FIELDS = frozenset(
    {
        "benchmark_version",
        "split",
        "dataset_sha256",
        "knowledge_manifest_sha256",
        "experiment_plan_sha256",
        "scorer_version",
        "scorer_manifest_sha256",
        "scorer_fixture_sha256",
        "scorer_spec_sha256",
        "scorer_implementation_sha256",
        "scorer_definition_commit_sha",
        "p4_schema_sha256",
        "application_under_test_sha",
        "evaluation_harness_sha",
        "freeze_commit_sha",
        "hosted_ci_run_id",
        "hosted_ci_head_sha",
        "evidence_gate",
        "evidence_gate_threshold",
        "grounding_candidate",
        "model_candidate",
        "model_revision",
        "retrieval_profile_version",
        "agent_prompt_version",
        "agent_graph_version",
        "grounding_finalizer_version",
        "run_id",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_lf_normalized(path: Path) -> str:
    """Hash a text artifact using the repository's normalized LF bytes."""

    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _canonical_p4_run_directories(root: Path) -> list[Path]:
    canonical_root = root / "evals/rag/v0.2/dev-evidence/canonical"
    if not canonical_root.exists():
        return []
    return sorted(
        path for path in canonical_root.iterdir() if path.is_dir() and "p4" in path.name.casefold()
    )


def audit_m5d_b2_preregistration(root: Path) -> dict[str, Any]:
    """Validate the frozen scorer/P4 plan without reading holdout question rows."""

    plan_path = root / PLAN_PATH
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    scorer = audit_scorer_v2(root)
    scorer_manifest_path = root / "evals/rag/v0.2/scorer-v2/manifest.json"
    p4_schema_path = root / "evals/rag/v0.2/scorer-v2/p4-output.schema.json"

    if plan.get("status") != "preregistration_only_no_results":
        raise ValueError("M5D-B2 freeze must remain a preregistration without results")
    if plan.get("candidate_ids") != ["P4_EVIDENCE_LINKED_SINGLE_PASS"]:
        raise ValueError("M5D-B2 must preregister exactly the single P4 candidate")
    if plan.get("execution", {}).get("split") != "dev" or plan["execution"].get("case_count") != 96:
        raise ValueError("P4 preregistration must target exactly the 96 DEV cases")
    if plan["execution"].get("release_holdout_access_allowed") is not False:
        raise ValueError("release holdout access must remain disabled")
    if plan["execution"].get("canonical_p4_inference_enabled_in_this_pr") is not False:
        raise ValueError("this preregistration change must not enable P4 inference")
    if plan["execution"].get("provider_inference_in_this_freeze_change") is not False:
        raise ValueError("provider inference is disallowed in the freeze change")
    if plan["execution"].get("p4_results_present_in_this_freeze_change") is not False:
        raise ValueError("P4 result artifacts are disallowed in the freeze change")
    if plan["execution"].get("selection_artifact_allowed") is not False:
        raise ValueError("selection.json is disallowed during M5D-B2")
    if plan["candidate"].get("status") != "preregistered_not_implemented":
        raise ValueError("P4 application behavior must remain unimplemented")
    if plan["candidate"].get("evaluation_labels_or_expected_facts_exposed_to_model") is not False:
        raise ValueError("benchmark answer keys must not be exposed to P4 model inputs")
    boundary = plan.get("production_boundary", {})
    if (
        boundary.get("production_default_prompt_or_finalizer_changed") is not False
        or boundary.get("production_model_provider_changed") is not False
        or boundary.get("production_retrieval_or_threshold_changed") is not False
        or boundary.get("production_tool_set_or_authorization_changed") is not False
        or boundary.get("p4_behavior_is_evaluation_candidate_only") is not True
    ):
        raise ValueError("the P4 preregistration must preserve production defaults")
    scorer_contract = plan.get("scorer_contract", {})
    manifest = scorer["manifest"]
    if scorer_contract.get("version") != manifest["scorer_version"]:
        raise ValueError("experiment plan references a different scorer version")
    if scorer_contract.get("manifest_path") != scorer_manifest_path.relative_to(root).as_posix():
        raise ValueError("experiment plan scorer-manifest path mismatch")
    if scorer_contract.get("fixture_path") != manifest["fixture_data_path"]:
        raise ValueError("experiment plan scorer-fixture path mismatch")
    if scorer_contract.get("fixture_sha256") != manifest["fixture_data_sha256"]:
        raise ValueError("experiment plan fixture hash does not match the scorer manifest")
    if scorer_contract.get("spec_path") != manifest["scorer_spec_path"]:
        raise ValueError("experiment plan scorer-spec path mismatch")
    if scorer_contract.get("spec_sha256") != manifest["scorer_spec_sha256"]:
        raise ValueError("experiment plan scorer-spec hash mismatch")
    if scorer_contract.get("implementation_path") != manifest["scorer_implementation_path"]:
        raise ValueError("experiment plan scorer-implementation path mismatch")
    if scorer_contract.get("implementation_sha256") != manifest["scorer_implementation_sha256"]:
        raise ValueError("experiment plan scorer-implementation hash mismatch")
    if scorer_contract.get("entrypoint") != manifest["scorer_entrypoint"]:
        raise ValueError("experiment plan scorer entrypoint mismatch")
    if plan["candidate"].get("schema_path") != p4_schema_path.relative_to(root).as_posix():
        raise ValueError("P4 output schema path mismatch")
    if plan["candidate"].get("schema_sha256") != _sha256(p4_schema_path):
        raise ValueError("P4 output schema SHA256 mismatch")
    manifest_sha = scorer_contract.get("manifest_sha256")
    if manifest_sha != _sha256(scorer_manifest_path):
        raise ValueError("experiment plan scorer-manifest SHA256 mismatch")
    if scorer_contract.get("definition_commit_sha") != manifest["scorer_frozen_at_commit_sha"]:
        raise ValueError("experiment plan scorer-definition commit mismatch")
    required_identity_fields = set(plan["run_identity"].get("required_fields", []))
    if not required_identity_fields >= REQUIRED_P4_IDENTITY_FIELDS:
        missing_identity_fields = sorted(REQUIRED_P4_IDENTITY_FIELDS - required_identity_fields)
        raise ValueError(
            "P4 run identity must bind every frozen provenance field: "
            + ", ".join(missing_identity_fields)
        )
    if plan["execution"]["freeze_gate"].get("required_hosted_jobs") != list(
        REQUIRED_HOSTED_CI_JOBS
    ):
        raise ValueError("freeze gate required jobs do not match the M5D-B2 CI contract")

    p4_run_directories = _canonical_p4_run_directories(root)
    canonical_p4_results = bool(p4_run_directories)

    selection_present = (root / "evals/rag/v0.2/selection.json").exists()
    if selection_present:
        raise ValueError("selection.json must remain absent during M5D-B2")

    return {
        "candidate_id": "P4_EVIDENCE_LINKED_SINGLE_PASS",
        "split": "dev",
        "case_count": 96,
        "canonical_p4_results_present": canonical_p4_results,
        "release_holdout_accessed": False,
        "selection_json_present": selection_present,
        "experiment_plan_sha256": _sha256(plan_path),
        "scorer_manifest_sha256": _sha256(scorer_manifest_path),
        "scorer_fixture_sha256": scorer["manifest"]["fixture_data_sha256"],
    }


def _safe_artifact_path(root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("P4 closeout artifact path escapes the repository")
    resolved_root = root.resolve()
    resolved_path = (resolved_root / candidate).resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError("P4 closeout artifact path escapes the repository")
    return resolved_path


def _find_artifact_references(value: Any, target: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("path") == target:
            found.append(value)
        for item in value.values():
            found.extend(_find_artifact_references(item, target))
    elif isinstance(value, list):
        for item in value:
            found.extend(_find_artifact_references(item, target))
    return found


def audit_m5d_b2_p4_closeout(root: Path) -> dict[str, Any]:
    """Validate the immutable final P4 execution-ineligible evidence package."""

    preregistration = audit_m5d_b2_preregistration(root)
    if not preregistration["canonical_p4_results_present"]:
        raise ValueError("the final canonical P4 closeout is missing")

    canonical_dirs = _canonical_p4_run_directories(root)
    if [path.name for path in canonical_dirs] != [P4_RUN_ID]:
        raise ValueError("canonical P4 run namespace does not match the final closeout")

    run_dir = canonical_dirs[0]
    closeout_path = run_dir / "p4-closeout.json"
    closeout = json.loads(closeout_path.read_text(encoding="utf-8"))
    expected_closeout = {
        "classification": P4_CLOSEOUT_CLASSIFICATION,
        "failure_class": "DETERMINISTIC_PROVIDER_PROTOCOL_INCOMPATIBILITY",
        "run_id": P4_RUN_ID,
        "run_identity_sha256": P4_RUN_IDENTITY_SHA256,
        "freeze_commit_sha": "77d04cd54143bd13b851ee2cbbe1f57766371fd0",
        "application_under_test_sha": "77d04cd54143bd13b851ee2cbbe1f57766371fd0",
        "evaluation_harness_sha": "77d04cd54143bd13b851ee2cbbe1f57766371fd0",
        "expected_cases": 96,
        "completed_cases": 1,
        "completed_case_ids": ["m5d-v02-shipping-001"],
        "blocked_case_id": "m5d-v02-shipping-002",
        "public_api_http_status": 503,
        "scoring_status": "NOT_SCORED_INCOMPLETE_EXECUTION",
        "quality_metrics": "NOT_COMPUTED",
        "quality_gate_failure": False,
        "stage4_dev_eligible": False,
        "m5d_c_eligible": False,
        "release_holdout_executed": False,
        "selection_json_present": False,
        "runner_retried_after_failure": False,
        "report_generated": False,
        "trace_sidecar_count": 1,
        "trace_matches_observation_agent_run_id": True,
    }
    for field, expected in expected_closeout.items():
        if closeout.get(field) != expected:
            raise ValueError(f"P4 closeout field mismatch: {field}")
    upstream = closeout.get("upstream_provider_error", {})
    if upstream != {
        "provider": "Groq",
        "http_status": 400,
        "error_type": "invalid_request_error",
        "parameter": "response_format",
        "message": "json mode cannot be combined with tool/function calling",
    }:
        raise ValueError("P4 closeout provider-protocol failure evidence mismatch")

    artifact_references = closeout.get("artifacts")
    if not isinstance(artifact_references, list):
        raise ValueError("P4 closeout artifact reference list is missing")
    run_relative = f"evals/rag/v0.2/dev-evidence/canonical/{P4_RUN_ID}"
    expected_reference_hashes = {
        f"{run_relative}/{relative}": digest for relative, digest in P4_ARTIFACT_SHA256.items()
    }
    reference_hashes = {
        item["path"]: item.get("sha256")
        for item in artifact_references
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if (
        len(artifact_references) != len(expected_reference_hashes)
        or reference_hashes != expected_reference_hashes
    ):
        raise ValueError("P4 closeout artifact references do not match the frozen artifact set")

    for relative, expected_sha in P4_ARTIFACT_SHA256.items():
        path = run_dir / relative
        if not path.is_file() or _sha256(path) != expected_sha:
            raise ValueError(f"P4 canonical artifact hash mismatch: {relative}")
    for item in artifact_references:
        path = _safe_artifact_path(root, item["path"])
        if not path.is_file() or _sha256(path) != item["sha256"]:
            raise ValueError(f"P4 closeout artifact reference hash mismatch: {item['path']}")

    checkpoint_path = run_dir / "grounded_cases.jsonl"
    observations = [
        json.loads(line)
        for line in checkpoint_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(observations) != 1:
        raise ValueError("P4 closeout checkpoint must contain exactly one observation")
    observation = observations[0]
    if (
        observation.get("case_id") != "m5d-v02-shipping-001"
        or observation.get("run_id") != P4_RUN_ID
        or observation.get("run_identity_sha256") != P4_RUN_IDENTITY_SHA256
    ):
        raise ValueError("P4 closeout observation identity mismatch")

    identity_sidecar = json.loads(
        (run_dir / "grounded_cases.jsonl.identity.json").read_text(encoding="utf-8")
    )
    if identity_sidecar.get("run_identity_sha256") != P4_RUN_IDENTITY_SHA256:
        raise ValueError("P4 closeout identity sidecar fingerprint mismatch")
    from verbaops.evaluation.m5d_run_identity import run_identity_sha256

    if run_identity_sha256(identity_sidecar.get("identity", {})) != P4_RUN_IDENTITY_SHA256:
        raise ValueError("P4 closeout identity payload fingerprint mismatch")

    trace_files = sorted((run_dir / "p4-traces").glob("*.json"))
    trace_reference = observation.get("p4_trace_artifact", {})
    if (
        len(trace_files) != 1
        or trace_reference.get("path") != f"p4-traces/{trace_files[0].name}"
        or trace_reference.get("sha256")
        != P4_ARTIFACT_SHA256["p4-traces/9f857402-47b7-4a96-b27e-1f6f81d698b1.json"]
    ):
        raise ValueError("P4 closeout trace sidecar reference mismatch")
    trace = json.loads(trace_files[0].read_text(encoding="utf-8"))
    if (
        trace.get("run_id") != P4_RUN_ID
        or trace.get("agent_run_id") != observation.get("agent_run_id")
        or trace_files[0].stem != observation.get("agent_run_id")
    ):
        raise ValueError("P4 closeout trace does not match the completed observation")

    interruption = json.loads((run_dir / "interruption.json").read_text(encoding="utf-8"))
    if (
        interruption.get("run_id") != P4_RUN_ID
        or interruption.get("run_identity_sha256") != P4_RUN_IDENTITY_SHA256
        or interruption.get("completed_case_count") != 1
        or interruption.get("blocked_case_id") != "m5d-v02-shipping-002"
        or interruption.get("holdout_executed") is not False
    ):
        raise ValueError("P4 closeout interruption record mismatch")

    selection_present = (root / "evals/rag/v0.2/selection.json").exists()
    if selection_present or (run_dir / "report.json").exists():
        raise ValueError("closed P4 must remain unscored with no report or selection artifact")

    decision_path = root / "evals/rag/v0.2/dev-decision.json"
    summary_path = root / "evals/rag/v0.2/dev-evidence/m5d-b-dev-summary.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if decision.get("canonical_evidence_status") != "COMPLETE":
        raise ValueError("M5D canonical evidence status must be COMPLETE")
    if summary.get("canonical_evidence_status") != "COMPLETE":
        raise ValueError("M5D summary canonical evidence status must be COMPLETE")
    summary_reference = decision.get("summary_artifact", {})
    if summary_reference.get("path") != summary_path.relative_to(
        root
    ).as_posix() or summary_reference.get("sha256") != _sha256_lf_normalized(summary_path):
        raise ValueError("M5D summary artifact hash reference mismatch")
    summary_rel = summary_path.relative_to(root).as_posix()
    summary_references = _find_artifact_references(decision, summary_rel)
    summary_sha = _sha256_lf_normalized(summary_path)
    if not summary_references or any(
        item.get("sha256") != summary_sha for item in summary_references
    ):
        raise ValueError("M5D summary artifact reference mismatch")
    closeout_rel = closeout_path.relative_to(root).as_posix()
    closeout_sha = _sha256(closeout_path)
    references = _find_artifact_references(decision, closeout_rel) + _find_artifact_references(
        summary, closeout_rel
    )
    if not references or any(item.get("sha256") != closeout_sha for item in references):
        raise ValueError("P4 closeout artifact hash reference mismatch")
    for document in (decision, summary):
        run = next(
            (
                record
                for record in document.get("canonical_runs", [])
                if record.get("run_id") == P4_RUN_ID
            ),
            None,
        )
        if (
            run is None
            or run.get("status") != P4_CLOSEOUT_CLASSIFICATION
            or run.get("completed_cases") != 1
            or run.get("total_cases") != 96
            or run.get("scoreable") is not False
            or run.get("scoring_status") != "NOT_SCORED_INCOMPLETE_EXECUTION"
        ):
            raise ValueError("M5D P4 canonical run decision mismatch")

    return {
        "run_id": P4_RUN_ID,
        "classification": P4_CLOSEOUT_CLASSIFICATION,
        "completed_cases": 1,
        "expected_cases": 96,
        "completed_case_ids": ["m5d-v02-shipping-001"],
        "blocked_case_id": "m5d-v02-shipping-002",
        "observation_count": len(observations),
        "trace_sidecar_count": len(trace_files),
        "report_generated": False,
        "quality_metrics_computed": False,
        "stage4_dev_eligible": False,
        "m5d_c_eligible": False,
        "release_holdout_executed": False,
        "selection_json_present": selection_present,
        "canonical_evidence_status": "COMPLETE",
        "artifact_hashes_valid": True,
        "p4_closeout_sha256": closeout_sha,
        "summary_sha256": summary_sha,
    }


def require_p4_inference_authorized(
    *,
    repo_root: Path,
    run_id: str,
    hosted_ci_run_id: int | None = None,
    freeze_commit_sha: str | None,
    hosted_ci_head_sha: str | None,
    hosted_ci_conclusion: str | None,
    job_conclusions: dict[str, str],
) -> None:
    """Require exact-head green hosted CI before a future canonical P4 request."""

    # Revalidate byte-bound scorer artifacts at the point of future inference
    # authorization, so later P4 commits cannot silently change scoring rules.
    if not isinstance(run_id, str) or not run_id.startswith("canonical-M0-P4-"):
        raise ValueError("a canonical M0 P4 run ID is required")
    audit_m5d_b2_preregistration(repo_root)
    p4_run_directories = _canonical_p4_run_directories(repo_root)
    closed_directories = [
        path for path in p4_run_directories if (path / "p4-closeout.json").is_file()
    ]
    if closed_directories:
        if any(path.name == run_id for path in closed_directories):
            raise ValueError("canonical P4 run is closed and cannot resume")
        raise ValueError("canonical P4 run is closed; no second P4 run is permitted")
    if p4_run_directories and [path.name for path in p4_run_directories] != [run_id]:
        raise ValueError("canonical P4 run namespace contains an unrelated run")
    if freeze_commit_sha is None or not re.fullmatch(r"[a-f0-9]{40}", freeze_commit_sha):
        raise ValueError("a committed full 40-hex freeze commit SHA is required")
    if (
        isinstance(hosted_ci_run_id, bool)
        or not isinstance(hosted_ci_run_id, int)
        or hosted_ci_run_id <= 0
    ):
        raise ValueError("a positive hosted CI run ID is required")
    if hosted_ci_head_sha != freeze_commit_sha:
        raise ValueError("hosted CI must run on the exact freeze commit")
    if hosted_ci_conclusion != "success":
        raise ValueError("successful hosted CI on the freeze commit is required")
    from verbaops.evaluation import m5d_run_identity

    current_head = m5d_run_identity.require_committed_behavior(
        repo_root, pre_experiment_sha=m5d_run_identity.PRE_EXPERIMENT_SHA
    )
    if current_head != freeze_commit_sha:
        raise ValueError("working-tree HEAD must equal the exact P4 freeze commit")
    missing_or_failed = [
        job for job in REQUIRED_HOSTED_CI_JOBS if job_conclusions.get(job) != "success"
    ]
    if missing_or_failed:
        raise ValueError(
            "required jobs must all succeed on the freeze commit: " + ", ".join(missing_or_failed)
        )


__all__ = [
    "P4_ARTIFACT_SHA256",
    "P4_CLOSEOUT_CLASSIFICATION",
    "P4_RUN_ID",
    "P4_RUN_IDENTITY_SHA256",
    "PLAN_PATH",
    "REQUIRED_HOSTED_CI_JOBS",
    "REQUIRED_P4_IDENTITY_FIELDS",
    "audit_m5d_b2_p4_closeout",
    "audit_m5d_b2_preregistration",
    "require_p4_inference_authorized",
]
