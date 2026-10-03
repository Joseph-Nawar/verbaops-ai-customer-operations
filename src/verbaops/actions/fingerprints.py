"""Versioned canonical proposal fingerprints."""

import hashlib
import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from verbaops.actions.models import ActionType, JSONValue

_FINGERPRINT_DOMAIN = "verbaops.action-proposal"
_FINGERPRINT_VERSION = 1
_MONEY_SCALE = Decimal("0.01")
_EXCLUDED_KEYS = frozenset(
    {
        "action_id",
        "action_request_id",
        "approval",
        "approval_required",
        "approval_status",
        "approved",
        "confirmation",
        "confirmation_required",
        "confirmation_status",
        "confirmed",
        "credential",
        "credentials",
        "gate",
        "gate_decision",
        "gate_decisions",
        "gates",
        "password",
        "prompt",
        "prompts",
        "secret",
        "secrets",
    }
)


def _canonical_value(value: JSONValue) -> object:
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        scaled = value.quantize(_MONEY_SCALE)
        if scaled != value:
            raise ValueError("decimal values must use at most two decimal places")
        return "0.00" if scaled == 0 else format(scaled, ".2f")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fingerprint timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, dict):
        return {
            key: _canonical_value(item)
            for key, item in value.items()
            if key.lower() not in _EXCLUDED_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite floats cannot be fingerprinted")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported fingerprint value: {type(value).__name__}")


def fingerprint_proposal(
    tenant_id: UUID,
    customer_id: UUID,
    action_type: ActionType,
    schema_version: str,
    target_ids: tuple[UUID, ...],
    normalized_payload: dict[str, JSONValue],
    material_snapshot: dict[str, JSONValue],
) -> str:
    """Return a lowercase SHA-256 digest over the immutable proposal material."""

    envelope = {
        "domain": _FINGERPRINT_DOMAIN,
        "version": _FINGERPRINT_VERSION,
        "tenant_id": str(tenant_id),
        "customer_id": str(customer_id),
        "action_type": action_type.value,
        "schema_version": schema_version,
        "target_ids": sorted(str(target_id) for target_id in target_ids),
        "normalized_payload": _canonical_value(normalized_payload),
        "material_snapshot": _canonical_value(material_snapshot),
    }
    canonical = json.dumps(
        envelope,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
