"""Provider-free M5D-B2 preregistration and future inference-unlock checks."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from verbaops.evaluation.rag_v02_scorer_v2 import audit_scorer_v2

PLAN_PATH = Path("evals/rag/v0.2/m5d-b2-experiment-plan.json")
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


def audit_m5d_b2_preregistration(
    root: Path, *, allow_current_p4_run_id: str | None = None
) -> dict[str, Any]:
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

    canonical_root = root / "evals/rag/v0.2/dev-evidence/canonical"
    p4_run_directories = (
        [
            path
            for path in canonical_root.iterdir()
            if path.is_dir() and "p4" in path.name.casefold()
        ]
        if canonical_root.exists()
        else []
    )
    canonical_p4_results = bool(p4_run_directories)
    if p4_run_directories and (
        not isinstance(allow_current_p4_run_id, str)
        or not allow_current_p4_run_id
        or Path(allow_current_p4_run_id).name != allow_current_p4_run_id
        or [path.name for path in p4_run_directories] != [allow_current_p4_run_id]
    ):
        raise ValueError("canonical P4 result artifacts exist outside the authorized run")

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
    # Generated observations in this exact run may exist during checkpoint
    # resumption. Any other P4 result namespace remains an authorization error.
    audit_m5d_b2_preregistration(repo_root, allow_current_p4_run_id=run_id)
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
    "PLAN_PATH",
    "REQUIRED_HOSTED_CI_JOBS",
    "REQUIRED_P4_IDENTITY_FIELDS",
    "audit_m5d_b2_preregistration",
    "require_p4_inference_authorized",
]
