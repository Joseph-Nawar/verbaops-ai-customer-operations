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
_MODE_FIELDS = {
    "p4_extractive_mode_active",
    "p4_extractive_mode_reason",
    "tool_path_entered",
    "p4_extractive_mode_deactivated_after_tool",
}
_RESPONSE_FIELDS = {
    "raw_structured_response",
    "parse_success",
    "parse_failure_reason",
    "proposed_claims",
    "claim_validation",
    "accepted_claims",
    "rendered_claims",
    "final_rendered_answer",
    "fallback_used",
    "fallback_reason",
}
_CLAIM_FIELDS = {"claim_text", "evidence_handle", "supporting_excerpt"}
_VALIDATION_FIELDS = {
    "index",
    "claim_text",
    "evidence_handle",
    "supporting_excerpt",
    "handle_valid",
    "excerpt_nonempty",
    "excerpt_matches_source",
    "claim_nonempty",
    "claim_matches_excerpt",
    "accepted",
    "rejection_reason",
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
    keys = set(diagnostics)
    allowed = _MODE_FIELDS | _RESPONSE_FIELDS
    if keys - allowed or not _MODE_FIELDS.issubset(keys):
        raise ValueError("P4 diagnostic field is not allowed or required")

    active = diagnostics["p4_extractive_mode_active"]
    mode_reason = diagnostics["p4_extractive_mode_reason"]
    tool_path_entered = diagnostics["tool_path_entered"]
    deactivated = diagnostics["p4_extractive_mode_deactivated_after_tool"]
    if not isinstance(active, bool) or not isinstance(tool_path_entered, bool):
        raise ValueError("P4 mode diagnostics must be booleans")
    if not isinstance(deactivated, bool) or deactivated != tool_path_entered:
        raise ValueError("P4 tool mode diagnostics are inconsistent")
    if not isinstance(mode_reason, str):
        raise ValueError("P4 mode reason is malformed")
    if active:
        if mode_reason != "selected_evidence_no_tool_path" or tool_path_entered:
            raise ValueError("active P4 mode has inconsistent provenance")
        if keys != _MODE_FIELDS | _RESPONSE_FIELDS:
            raise ValueError("active P4 mode is missing response diagnostics")
    else:
        if mode_reason not in {"no_selected_knowledge_evidence", "commerce_tool_path"}:
            raise ValueError("inactive P4 mode has an unknown reason")
        if (mode_reason == "commerce_tool_path") != tool_path_entered:
            raise ValueError("inactive P4 mode reason does not match tool state")
        if keys != _MODE_FIELDS:
            raise ValueError("inactive P4 mode must not retain response diagnostics")

    if active:
        raw_response = diagnostics["raw_structured_response"]
        parse_success = diagnostics["parse_success"]
        parse_failure = diagnostics["parse_failure_reason"]
        proposed = diagnostics["proposed_claims"]
        validations = diagnostics["claim_validation"]
        accepted = diagnostics["accepted_claims"]
        rendered = diagnostics["rendered_claims"]
        final_answer = diagnostics["final_rendered_answer"]
        fallback_used = diagnostics["fallback_used"]
        fallback_reason = diagnostics["fallback_reason"]
        allowed_parse_failures = {
            "invalid_json",
            "invalid_p4_schema",
            "missing_or_blank_terminal_content",
        }
        allowed_fallbacks = allowed_parse_failures | {
            "all_claims_rejected",
            "citation_finalizer_rejected_claims",
        }
        if raw_response is not None and not isinstance(raw_response, str):
            raise ValueError("P4 response diagnostics are malformed")
        if not isinstance(parse_success, bool):
            raise ValueError("P4 response diagnostics are malformed")
        if not isinstance(rendered, str) or not isinstance(final_answer, str):
            raise ValueError("P4 response diagnostics are malformed")
        if not isinstance(fallback_used, bool):
            raise ValueError("P4 response diagnostics are malformed")
        if parse_failure is not None and (
            not isinstance(parse_failure, str) or parse_failure not in allowed_parse_failures
        ):
            raise ValueError("P4 response diagnostics are malformed")
        if fallback_reason is not None and (
            not isinstance(fallback_reason, str) or fallback_reason not in allowed_fallbacks
        ):
            raise ValueError("P4 response diagnostics are malformed")
        if fallback_used != (fallback_reason is not None):
            raise ValueError("P4 response diagnostics are malformed")
        if parse_success != (parse_failure is None):
            raise ValueError("P4 response diagnostics are malformed")
        if not all(isinstance(items, list) for items in (proposed, validations, accepted)):
            raise ValueError("P4 response diagnostics are malformed")
        if any(
            not isinstance(claim, dict) or set(claim) != _CLAIM_FIELDS
            for claim in (*proposed, *accepted)
        ):
            raise ValueError("P4 response diagnostics are malformed")
        if any(
            not isinstance(item, dict) or set(item) != _VALIDATION_FIELDS for item in validations
        ):
            raise ValueError("P4 response diagnostics are malformed")
        if any(
            not isinstance(item[field], str)
            for item in validations
            for field in ("claim_text", "evidence_handle", "supporting_excerpt")
        ):
            raise ValueError("P4 response diagnostics are malformed")
        if any(
            not isinstance(claim[field], str)
            for claim in (*proposed, *accepted)
            for field in _CLAIM_FIELDS
        ):
            raise ValueError("P4 response diagnostics are malformed")
        if len(proposed) != len(validations):
            raise ValueError("P4 response diagnostics are malformed")
        rejection_reasons = {
            "invalid_handle",
            "empty_excerpt",
            "excerpt_mismatch",
            "empty_claim",
            "claim_not_substring",
        }
        for index, item in enumerate(validations):
            if (
                not isinstance(item["index"], int)
                or isinstance(item["index"], bool)
                or item["index"] != index
            ):
                raise ValueError("P4 response diagnostics are malformed")
            if any(
                not isinstance(item[field], bool)
                for field in ("handle_valid", "excerpt_nonempty", "claim_nonempty", "accepted")
            ):
                raise ValueError("P4 response diagnostics are malformed")
            if any(
                item[field] is not None and not isinstance(item[field], bool)
                for field in ("excerpt_matches_source", "claim_matches_excerpt")
            ):
                raise ValueError("P4 response diagnostics are malformed")
            if item["rejection_reason"] is not None and (
                not isinstance(item["rejection_reason"], str)
                or item["rejection_reason"] not in rejection_reasons
            ):
                raise ValueError("P4 response diagnostics are malformed")
            expected_rejection = (
                "invalid_handle"
                if not item["handle_valid"]
                else "empty_excerpt"
                if not item["excerpt_nonempty"]
                else "excerpt_mismatch"
                if item["excerpt_matches_source"] is not True
                else "empty_claim"
                if not item["claim_nonempty"]
                else "claim_not_substring"
                if item["claim_matches_excerpt"] is not True
                else None
            )
            if item["rejection_reason"] != expected_rejection:
                raise ValueError("P4 response diagnostics are malformed")
            if (item["rejection_reason"] is None) != item["accepted"]:
                raise ValueError("P4 response diagnostics are malformed")
            proposed_claim = proposed[index]
            if any(
                item[field] != proposed_claim[field]
                for field in ("claim_text", "evidence_handle", "supporting_excerpt")
            ):
                raise ValueError("P4 response diagnostics are malformed")
        accepted_from_validation = [
            proposed[index] for index, item in enumerate(validations) if item["accepted"]
        ]
        if accepted != accepted_from_validation:
            raise ValueError("P4 response diagnostics are malformed")
        expected_rendered = "\n".join(
            f"{claim['claim_text']} [[{claim['evidence_handle']}]]" for claim in accepted
        )
        if rendered != expected_rendered:
            raise ValueError("P4 response diagnostics are malformed")
        if (fallback_reason == "all_claims_rejected") != (parse_success and not accepted):
            raise ValueError("P4 response diagnostics are malformed")
        if fallback_reason == "citation_finalizer_rejected_claims" and not accepted:
            raise ValueError("P4 response diagnostics are malformed")
        if not parse_success and (
            proposed or validations or accepted or fallback_reason != parse_failure
        ):
            raise ValueError("P4 response diagnostics are malformed")

    sanitized: dict[str, Any] = {}
    for key, value in diagnostics.items():
        if key in {"proposed_claims", "accepted_claims"} and (
            not isinstance(value, list)
            or any(not isinstance(claim, dict) or set(claim) != _CLAIM_FIELDS for claim in value)
        ):
            raise ValueError("P4 claim diagnostics are malformed")
        if key == "claim_validation" and (
            not isinstance(value, list)
            or any(not isinstance(item, dict) or set(item) != _VALIDATION_FIELDS for item in value)
        ):
            raise ValueError("P4 validation diagnostics are malformed")
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


__all__ = ["P4TraceArtifact", "P4TraceStore", "verify_p4_trace_records"]
