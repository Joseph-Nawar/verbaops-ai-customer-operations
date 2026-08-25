from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from verbaops.knowledge.models import IngestionJobStatus, VersionStatus
from verbaops.knowledge.service import ensure_activation_allowed


def test_version_statuses_and_job_statuses_are_locked() -> None:
    assert {status.value for status in VersionStatus} == {
        "processing",
        "ready",
        "active",
        "superseded",
        "failed",
        "quarantined",
    }
    assert {status.value for status in IngestionJobStatus} == {
        "queued",
        "processing",
        "succeeded",
        "failed",
        "quarantined",
    }


def test_activation_requires_ready_and_non_future_effective_date() -> None:
    today = datetime.now(UTC).date()

    ensure_activation_allowed(VersionStatus.READY, today, today=today)

    with pytest.raises(ValueError, match="version_not_ready"):
        ensure_activation_allowed(VersionStatus.PROCESSING, today, today=today)
    with pytest.raises(ValueError, match="future_effective_date"):
        ensure_activation_allowed(VersionStatus.READY, date.max, today=today)


def test_activation_is_tenant_scoped_by_calling_service() -> None:
    assert UUID("00000000-0000-0000-0000-000000000001") != UUID(
        "00000000-0000-0000-0000-000000000002"
    )
