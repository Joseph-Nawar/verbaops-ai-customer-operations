"""Safe interruption types for resumable genuine evaluation runs."""

from __future__ import annotations

from uuid import UUID


class ProviderExecutionError(RuntimeError):
    """A provider-backed case could not produce an evaluation observation."""


class ProviderQuotaExceeded(ProviderExecutionError):
    """A provider rate/token quota interrupted the current evaluation run."""

    reason = "provider_quota"

    def __init__(
        self,
        *,
        retry_after_seconds: int | None = None,
        reset_metadata: str | None = None,
    ) -> None:
        super().__init__("provider quota interrupted evaluation")
        self.run_id: UUID | None = None
        self.completed_case_count = 0
        self.remaining_case_count = 0
        self.retry_after_seconds = retry_after_seconds
        self.reset_metadata = reset_metadata


def interruption_summary(
    *,
    reason: str,
    completed_case_count: int,
    remaining_case_count: int,
    retry_after_seconds: int | None = None,
    reset_metadata: str | None = None,
) -> dict[str, object]:
    """Build a non-secret persisted marker for an incomplete evaluation run."""

    summary: dict[str, object] = {
        "status": "interrupted",
        "reason": reason,
        "completed_case_count": completed_case_count,
        "remaining_case_count": remaining_case_count,
    }
    if retry_after_seconds is not None:
        summary["retry_after_seconds"] = retry_after_seconds
    if reset_metadata is not None:
        summary["reset_metadata"] = reset_metadata
    return summary
