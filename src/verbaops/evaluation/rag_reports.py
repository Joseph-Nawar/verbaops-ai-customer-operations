"""Stable serialization helpers for RAG benchmark evidence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 12)


def serialize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Return JSON-safe report data without mutating caller-owned state."""

    return dict(report)


__all__ = ["percentile", "serialize_report"]
