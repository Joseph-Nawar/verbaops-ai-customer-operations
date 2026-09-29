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

_SHA1 = re.compile(r"^[a-f0-9]{40}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
PRE_EXPERIMENT_SHA = "347eccfd7aaa22332bdf36ee396715133b716b9c"
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
_GENERATED_ROOTS = (
    PurePosixPath("evals/rag/v0.2/dev-evidence/canonical"),
    PurePosixPath("artifacts/m5d"),
)


def _validated_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in _IDENTITY_FIELDS if field not in identity]
    if missing:
        raise ValueError(f"M5D run identity is missing fields: {', '.join(missing)}")
    normalized = {field: identity[field] for field in _IDENTITY_FIELDS}
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
    for field in _IDENTITY_FIELDS:
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


def require_canonical_run_directory(repo_root: Path, run_dir: Path, *, run_id: str) -> Path:
    """Require a fresh run namespace below the canonical evidence root."""

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
    "PRE_EXPERIMENT_SHA",
    "artifact_reference",
    "bind_checkpoint_identity",
    "load_checkpoint_records",
    "require_canonical_run_directory",
    "require_committed_behavior",
    "run_identity_sha256",
    "validate_dev_decision_provenance",
    "verify_artifact_references",
]
