"""Narrow sanitized sidecar storage for canonical P4 evaluation diagnostics."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_TOP_LEVEL_FIELDS = {"schema_version", "run_id", "agent_run_id", "diagnostics"}
_FROZEN_P4_TRACE_FIELDS = frozenset(
    {
        "raw_structured_model_response",
        "parse_success",
        "parse_failure_reason",
        "proposed_claims",
        "proposed_evidence_handle_per_claim",
        "proposed_excerpt_per_claim",
        "handle_validation_result_per_claim",
        "excerpt_validation_result_per_claim",
        "deterministic_rejection_reason_per_claim",
        "rendered_final_claims",
        "p4_extractive_mode_active",
        "p4_extractive_mode_reason",
        "tool_path_entered",
        "p4_extractive_mode_deactivated_after_tool",
        "fallback_used",
        "fallback_reason",
    }
)
_FROZEN_P4_MODE_REASONS = frozenset(
    {
        "selected_evidence_knowledge_path",
        "no_selected_knowledge_evidence",
        "commerce_tool_call_emitted",
        "deactivated_after_commerce_tool",
        "terminal_tool_answer_bypassed_validator",
        "terminal_knowledge_answer_validated",
        "malformed_or_invalid_structured_knowledge_output",
        "all_claims_rejected_safe_fallback",
    }
)
_CLAIM_FIELDS = {"claim_text", "evidence_handle", "supporting_excerpt"}
_PARSE_FAILURES = {
    "invalid_json",
    "invalid_p4_schema",
    "missing_or_blank_terminal_content",
}
_REJECTION_REASONS = {
    "invalid_handle",
    "empty_excerpt",
    "excerpt_mismatch",
    "empty_claim",
    "claim_not_substring",
}
_FALLBACK_REASONS = _PARSE_FAILURES | {
    "all_claims_rejected",
    "citation_finalizer_rejected_claims",
}
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|access[_-]?token|authorization|password|secret|credential)"
    r"[\"']?\s*:\s*[\"']?)([^\"'\s,}\]]+)"
)
_BEARER_VALUE = re.compile(r"(?i)(\bbearer\s+)[^\s,;\"']+")
_TOKEN_VALUE = re.compile(r"\b(?:gsk_[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{8,})\b")


@dataclass(frozen=True, slots=True)
class P4TraceArtifact:
    path: Path
    relative_path: str
    sha256: str
    payload: dict[str, Any]


def frozen_p4_observability_contract() -> tuple[frozenset[str], frozenset[str]]:
    """Return the plan-checked trace contract without requiring eval files at runtime."""

    return _FROZEN_P4_TRACE_FIELDS, _FROZEN_P4_MODE_REASONS


class P4TraceStore:
    """Read/write one sanitized sidecar per actual agent run ID."""

    def __init__(
        self,
        run_directory: Path,
        run_id: str,
        *,
        secrets_to_hide: Iterable[str] = (),
    ) -> None:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("invalid P4 canonical run ID")
        self.run_id = run_id
        if run_directory.is_symlink():
            raise ValueError("P4 trace run directory may not be a symlink")
        self.run_directory = run_directory.resolve()
        if self.run_directory.name != run_id:
            raise ValueError("P4 trace directory must match canonical run ID")
        trace_directory = self.run_directory / "p4-traces"
        if trace_directory.is_symlink():
            raise ValueError("P4 trace directory may not be a symlink")
        trace_directory.mkdir(parents=True, exist_ok=True)
        self.trace_directory = trace_directory.resolve()
        if not self.trace_directory.is_relative_to(self.run_directory):
            raise ValueError("P4 trace path escapes canonical run directory")
        self._secrets_to_hide = tuple(secret for secret in secrets_to_hide if secret)

    def write(self, agent_run_id: UUID, diagnostics: Mapping[str, Any]) -> Path:
        agent_id = _normalize_agent_run_id(agent_run_id)
        path = self._path_for(agent_id)
        if path.exists():
            raise FileExistsError("P4 trace already exists for agent run")
        clean_diagnostics = _sanitize_diagnostics(diagnostics, self._secrets_to_hide)
        payload = {
            "schema_version": 1,
            "run_id": self.run_id,
            "agent_run_id": agent_id,
            "diagnostics": clean_diagnostics,
        }
        try:
            encoded = (
                json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
            )
        except (TypeError, ValueError):
            raise ValueError("P4 trace diagnostics are not JSON-safe") from None

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{agent_id}.", suffix=".tmp", dir=self.trace_directory
        )
        temporary_path = Path(temporary_name)
        created = False
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                raise FileExistsError("P4 trace already exists for agent run")
            os.link(temporary_path, path)
            created = True
            temporary_path.unlink()
            _fsync_directory(self.trace_directory)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            if created:
                path.unlink(missing_ok=True)
            raise
        return path

    def read(self, agent_run_id: UUID) -> P4TraceArtifact:
        agent_id = _normalize_agent_run_id(agent_run_id)
        path = self._path_for(agent_id)
        if not path.is_file():
            raise FileNotFoundError("P4 trace is missing for agent run")
        try:
            raw_bytes = path.read_bytes()
            payload = json.loads(raw_bytes)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("P4 trace sidecar is malformed") from None
        if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_FIELDS:
            raise ValueError("P4 trace sidecar has an invalid shape")
        if (
            not isinstance(payload.get("schema_version"), int)
            or isinstance(payload.get("schema_version"), bool)
            or payload.get("schema_version") != 1
            or payload.get("run_id") != self.run_id
            or payload.get("agent_run_id") != agent_id
        ):
            raise ValueError("P4 trace sidecar identity does not match the requested run")
        diagnostics = payload.get("diagnostics")
        if not isinstance(diagnostics, dict):
            raise ValueError("P4 trace sidecar diagnostics are malformed")
        try:
            sanitized = _sanitize_diagnostics(diagnostics, self._secrets_to_hide)
        except ValueError:
            raise ValueError("P4 trace sidecar diagnostics are malformed") from None
        if sanitized != diagnostics:
            raise ValueError("P4 trace sidecar contains unsanitized values")
        return P4TraceArtifact(
            path=path,
            relative_path=path.relative_to(self.run_directory).as_posix(),
            sha256=hashlib.sha256(raw_bytes).hexdigest(),
            payload=payload,
        )

    def _path_for(self, agent_run_id: str) -> Path:
        path = self.trace_directory / f"{agent_run_id}.json"
        resolved = path.resolve()
        if not resolved.is_relative_to(self.trace_directory):
            raise ValueError("P4 trace path escapes canonical run directory")
        return path


def verify_p4_trace_records(
    repo_root: Path,
    run_directory: Path,
    run_id: str,
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Verify every observation is bound to its immutable agent trace sidecar."""

    root = repo_root.resolve()
    if run_directory.is_symlink():
        raise ValueError("P4 trace run directory is invalid")
    run_path = run_directory.resolve()
    if run_path.name != run_id:
        raise ValueError("P4 trace run directory is invalid")
    canonical_root = (root / "evals/rag/v0.2/dev-evidence/canonical").resolve()
    try:
        run_path.relative_to(canonical_root)
    except ValueError as error:
        raise ValueError("P4 trace run directory escapes canonical evidence root") from error
    store = P4TraceStore(run_path, run_id)
    seen_agent_ids: set[str] = set()
    references: list[dict[str, str]] = []
    for record in records:
        agent_run_id = record.get("agent_run_id")
        if not isinstance(agent_run_id, str) or agent_run_id in seen_agent_ids:
            raise ValueError("P4 observations have a missing or duplicate agent run ID")
        seen_agent_ids.add(agent_run_id)
        expected = record.get("p4_trace_artifact")
        if not isinstance(expected, Mapping):
            raise ValueError("P4 observation is missing its trace artifact reference")
        artifact = store.read(UUID(agent_run_id))
        if (
            expected.get("path") != artifact.relative_path
            or expected.get("sha256") != artifact.sha256
        ):
            raise ValueError("P4 observation trace artifact reference does not match sidecar bytes")
        if record.get("p4_diagnostics") != artifact.payload["diagnostics"]:
            raise ValueError("P4 observation diagnostics do not match its trace sidecar")
        try:
            repository_path = artifact.path.resolve().relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError("P4 trace artifact escapes repository root") from error
        references.append({"path": repository_path, "sha256": artifact.sha256})
    sidecar_entries = list(store.trace_directory.iterdir())
    expected_names = {f"{agent_run_id}.json" for agent_run_id in seen_agent_ids}
    actual_sidecars = {
        path.stem for path in sidecar_entries if path.suffix == ".json" and path.is_file()
    }
    if actual_sidecars != seen_agent_ids:
        raise ValueError("P4 trace sidecars do not exactly match checkpoint observations")
    if any(not path.is_file() or path.name not in expected_names for path in sidecar_entries):
        raise ValueError("P4 trace directory contains unrecognized files")
    return references


def _normalize_agent_run_id(agent_run_id: UUID) -> str:
    try:
        normalized = str(UUID(str(agent_run_id)))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("invalid P4 agent run ID") from None
    if str(agent_run_id) != normalized:
        raise ValueError("invalid P4 agent run ID")
    return normalized


def _sanitize_diagnostics(
    diagnostics: Mapping[str, Any], secrets_to_hide: tuple[str, ...]
) -> dict[str, Any]:
    if not isinstance(diagnostics, Mapping):
        raise ValueError("P4 diagnostics must be an object")
    required_fields, allowed_reasons = frozen_p4_observability_contract()
    if set(diagnostics) != required_fields:
        raise ValueError("P4 diagnostic fields do not match the frozen observability contract")

    active = diagnostics["p4_extractive_mode_active"]
    mode_reason = diagnostics["p4_extractive_mode_reason"]
    tool_path_entered = diagnostics["tool_path_entered"]
    deactivated = diagnostics["p4_extractive_mode_deactivated_after_tool"]
    if not isinstance(active, bool) or not isinstance(tool_path_entered, bool):
        raise ValueError("P4 mode diagnostics must be booleans")
    if not isinstance(deactivated, bool) or deactivated != tool_path_entered:
        raise ValueError("P4 tool mode diagnostics are inconsistent")
    if not isinstance(mode_reason, str) or mode_reason not in allowed_reasons:
        raise ValueError("P4 mode reason is outside the frozen vocabulary")

    raw_response = diagnostics["raw_structured_model_response"]
    parse_success = diagnostics["parse_success"]
    parse_failure = diagnostics["parse_failure_reason"]
    proposed = diagnostics["proposed_claims"]
    handles = diagnostics["proposed_evidence_handle_per_claim"]
    excerpts = diagnostics["proposed_excerpt_per_claim"]
    handle_results = diagnostics["handle_validation_result_per_claim"]
    excerpt_results = diagnostics["excerpt_validation_result_per_claim"]
    rejection_reasons = diagnostics["deterministic_rejection_reason_per_claim"]
    rendered = diagnostics["rendered_final_claims"]
    fallback_used = diagnostics["fallback_used"]
    fallback_reason = diagnostics["fallback_reason"]

    if raw_response is not None and not isinstance(raw_response, str):
        raise ValueError("P4 response diagnostics are malformed")
    if parse_success is not None and not isinstance(parse_success, bool):
        raise ValueError("P4 response diagnostics are malformed")
    if parse_failure is not None and (
        not isinstance(parse_failure, str) or parse_failure not in _PARSE_FAILURES
    ):
        raise ValueError("P4 response diagnostics are malformed")
    if not isinstance(rendered, str) or not isinstance(fallback_used, bool):
        raise ValueError("P4 response diagnostics are malformed")
    if fallback_reason is not None and (
        not isinstance(fallback_reason, str) or fallback_reason not in _FALLBACK_REASONS
    ):
        raise ValueError("P4 response diagnostics are malformed")
    if fallback_used != (fallback_reason is not None):
        raise ValueError("P4 response diagnostics are malformed")
    if not all(
        isinstance(items, list)
        for items in (
            proposed,
            handles,
            excerpts,
            handle_results,
            excerpt_results,
            rejection_reasons,
        )
    ):
        raise ValueError("P4 response diagnostics are malformed")
    if any(
        not isinstance(claim, dict)
        or set(claim) != _CLAIM_FIELDS
        or any(not isinstance(claim[field], str) for field in _CLAIM_FIELDS)
        for claim in proposed
    ):
        raise ValueError("P4 claim diagnostics are malformed")
    count = len(proposed)
    if any(
        len(items) != count
        for items in (handles, excerpts, handle_results, excerpt_results, rejection_reasons)
    ):
        raise ValueError("P4 per-claim diagnostic arrays are inconsistent")
    if handles != [claim["evidence_handle"] for claim in proposed] or excerpts != [
        claim["supporting_excerpt"] for claim in proposed
    ]:
        raise ValueError("P4 per-claim diagnostic arrays do not match proposed claims")
    if any(not isinstance(value, bool) for value in handle_results):
        raise ValueError("P4 handle validation results are malformed")
    if any(value is not None and not isinstance(value, bool) for value in excerpt_results):
        raise ValueError("P4 excerpt validation results are malformed")
    if any(
        value is not None and (not isinstance(value, str) or value not in _REJECTION_REASONS)
        for value in rejection_reasons
    ):
        raise ValueError("P4 deterministic rejection reasons are malformed")

    accepted: list[dict[str, str]] = []
    for index, claim in enumerate(proposed):
        claim_text = claim["claim_text"]
        excerpt = excerpts[index]
        expected_rejection = (
            "invalid_handle"
            if not handle_results[index]
            else "empty_excerpt"
            if not excerpt.strip()
            else "excerpt_mismatch"
            if excerpt_results[index] is not True
            else "empty_claim"
            if not claim_text.strip()
            else "claim_not_substring"
            if claim_text not in excerpt
            else None
        )
        if rejection_reasons[index] != expected_rejection:
            raise ValueError("P4 deterministic rejection reason disagrees with validation results")
        if expected_rejection is None:
            accepted.append(claim)
    expected_rendered = "\n".join(
        f"{claim['claim_text']} [[{claim['evidence_handle']}]]" for claim in accepted
    )
    if rendered != expected_rendered:
        raise ValueError("P4 rendered claims do not match accepted-claim diagnostics")

    if active:
        if tool_path_entered or not isinstance(parse_success, bool):
            raise ValueError("active P4 mode has inconsistent response diagnostics")
        if parse_success != (parse_failure is None):
            raise ValueError("P4 parse result is inconsistent")
        if not parse_success:
            if (
                mode_reason != "malformed_or_invalid_structured_knowledge_output"
                or proposed
                or rendered
                or not fallback_used
                or fallback_reason != parse_failure
            ):
                raise ValueError("malformed P4 response diagnostics are inconsistent")
        elif not accepted:
            if (
                mode_reason != "all_claims_rejected_safe_fallback"
                or not fallback_used
                or fallback_reason != "all_claims_rejected"
            ):
                raise ValueError("all-claims-rejected P4 diagnostics are inconsistent")
        elif mode_reason != "terminal_knowledge_answer_validated":
            raise ValueError("terminal P4 knowledge diagnostics have an invalid reason")
    else:
        expected_reason = (
            "terminal_tool_answer_bypassed_validator"
            if tool_path_entered
            else "no_selected_knowledge_evidence"
        )
        if (
            mode_reason != expected_reason
            or raw_response is not None
            or parse_success is not None
            or parse_failure is not None
            or proposed
            or handles
            or excerpts
            or handle_results
            or excerpt_results
            or rejection_reasons
            or rendered
            or fallback_used
            or fallback_reason is not None
        ):
            raise ValueError("inactive P4 diagnostics must use not-applicable response values")

    sanitized: dict[str, Any] = {}
    for key, value in diagnostics.items():
        sanitized[key] = _sanitize_value(value, secrets_to_hide)
    return sanitized


def _sanitize_value(value: Any, secrets_to_hide: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        value = _SENSITIVE_ASSIGNMENT.sub(r"\1[redacted]", value)
        value = _BEARER_VALUE.sub(r"\1[redacted]", value)
        value = _TOKEN_VALUE.sub("[redacted]", value)
        for secret in secrets_to_hide:
            value = value.replace(secret, "[redacted]")
        return value
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_sanitize_value(item, secrets_to_hide) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item, secrets_to_hide) for key, item in value.items()}
    raise ValueError("P4 trace contains a non-serializable value")


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "P4TraceArtifact",
    "P4TraceStore",
    "frozen_p4_observability_contract",
    "verify_p4_trace_records",
]
