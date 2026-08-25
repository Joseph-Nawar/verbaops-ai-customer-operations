"""Provider-free recovery export and baseline finalization for completed runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from verbaops.evaluation.baseline import (
    EXPECTED_CASE_COUNT,
    build_baseline_artifact,
    contains_secret_material,
    validate_baseline_artifact,
    write_baseline_artifacts,
)
from verbaops.evaluation.models import CaseEvaluationResult, EvaluationSummary

__all__ = [
    "RecoveryBundleError",
    "finalize_recovery_bundle",
    "load_recovery_bundle",
    "write_baseline_artifacts",
    "write_recovery_bundle",
]


class RecoveryBundleError(ValueError):
    """Raised when a local recovery bundle is incomplete or unsafe."""


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _json_line(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"


def _validate_pair(summary: EvaluationSummary, results: Sequence[CaseEvaluationResult]) -> None:
    if summary.case_count != EXPECTED_CASE_COUNT or len(results) != EXPECTED_CASE_COUNT:
        raise RecoveryBundleError("recovery bundle must contain exactly 120 cases")
    if len({result.case_id for result in results}) != EXPECTED_CASE_COUNT:
        raise RecoveryBundleError("recovery bundle contains duplicate case IDs")
    if summary.run_id is None:
        raise RecoveryBundleError("recovery bundle is missing its run ID")
    if summary.dataset_version != "text-agent-v0.1":
        raise RecoveryBundleError("recovery bundle dataset is not text-agent-v0.1")


def write_recovery_bundle(
    bundle_dir: Path,
    summary: EvaluationSummary,
    results: Sequence[CaseEvaluationResult],
    execution_git_sha: str,
    *,
    secret_values: Iterable[str] = (),
    runtime_metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Export sanitized completed-run evidence before any destructive teardown."""

    _validate_pair(summary, results)
    result_values = [result.model_dump(mode="json") for result in results]
    run_value = {
        "run_id": str(summary.run_id),
        "execution_git_sha": execution_git_sha,
        "summary": summary.model_dump(mode="json"),
        "result_count": len(result_values),
        "result_sha256": hashlib.sha256(
            "".join(_json_line(result) for result in result_values).encode("utf-8")
        ).hexdigest(),
        "runtime": dict(runtime_metadata or {}),
    }
    secrets = tuple(secret_values)
    results_text = "".join(_json_line(result) for result in result_values)
    if contains_secret_material(run_value, secrets) or contains_secret_material(
        results_text, secrets
    ):
        raise RecoveryBundleError("recovery bundle contains secret material")
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "run.json").write_text(_json_text(run_value), encoding="utf-8")
    (bundle_dir / "results.jsonl").write_text(results_text, encoding="utf-8")
    (bundle_dir / "manifest.json").write_text(
        _json_text(
            {
                "run_id": str(summary.run_id),
                "case_count": len(result_values),
                "unique_case_count": len({result["case_id"] for result in result_values}),
                "dataset_version": summary.dataset_version,
                "dataset_sha256": summary.dataset_sha256,
                "result_sha256": run_value["result_sha256"],
            }
        ),
        encoding="utf-8",
    )
    return bundle_dir


def load_recovery_bundle(
    bundle_dir: Path,
) -> tuple[UUID, str, EvaluationSummary, tuple[CaseEvaluationResult, ...]]:
    """Read and validate a recovery export without invoking any provider."""

    try:
        run_value = json.loads((bundle_dir / "run.json").read_text(encoding="utf-8"))
        raw_results = (bundle_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
        summary = EvaluationSummary.model_validate(run_value["summary"])
        run_id = UUID(run_value["run_id"])
        execution_sha = run_value["execution_git_sha"]
        results = tuple(
            CaseEvaluationResult.model_validate(json.loads(line)) for line in raw_results
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RecoveryBundleError("recovery bundle is unreadable") from error
    if run_id != summary.run_id or not isinstance(execution_sha, str) or not execution_sha:
        raise RecoveryBundleError("recovery bundle run identity is inconsistent")
    _validate_pair(summary, results)
    expected_hash = hashlib.sha256(
        "".join(_json_line(result.model_dump(mode="json")) for result in results).encode("utf-8")
    ).hexdigest()
    if run_value.get("result_sha256") != expected_hash:
        raise RecoveryBundleError("recovery bundle results checksum is invalid")
    return run_id, execution_sha, summary, results


def finalize_recovery_bundle(
    bundle_dir: Path,
    json_path: Path,
    markdown_path: Path,
    *,
    secret_values: Iterable[str] = (),
) -> EvaluationSummary:
    """Promote an already-completed run; this function has no provider boundary."""

    run_id, execution_sha, summary, results = load_recovery_bundle(bundle_dir)
    artifact = build_baseline_artifact(summary, results, execution_sha, datetime.now(UTC))
    write_baseline_artifacts(artifact, json_path, markdown_path, secret_values=secret_values)
    validated = validate_baseline_artifact(json.loads(json_path.read_text(encoding="utf-8")))
    if validated.case_count != len(results) or validated.case_count != EXPECTED_CASE_COUNT:
        raise RecoveryBundleError("promoted baseline result count is invalid")
    if validated.capability_alias == "deterministic-fixture":
        raise RecoveryBundleError("deterministic-fixture cannot be promoted")
    if validated.baseline_name != "stage4-agent-v0.1-baseline":
        raise RecoveryBundleError("promoted baseline name is invalid")
    if validated.execution_git_sha != execution_sha or summary.run_id != run_id:
        raise RecoveryBundleError("promoted baseline identity is inconsistent")
    return summary
