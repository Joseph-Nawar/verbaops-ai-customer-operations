from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI

from tests.api.conftest import build_context, build_provider, request
from verbaops.auth.context import Role
from verbaops.config.settings import Settings
from verbaops.knowledge.models import (
    IngestionIdentifiers,
    IngestionJobStatus,
    JobView,
    VersionMetadata,
    VersionStatus,
)

TENANT = UUID("30000000-0000-0000-0000-000000000002")
DOC = UUID("40000000-0000-0000-0000-000000000001")
VERSION = UUID("40000000-0000-0000-0000-000000000002")
JOB = UUID("40000000-0000-0000-0000-000000000003")


class FakeKnowledgeService:
    async def attach_task_id(self, tenant_id: UUID, job_id: UUID, task_id: str) -> None:
        assert tenant_id == TENANT
        assert job_id == JOB
        assert task_id == "celery-task-1"

    async def queue_upload(
        self, tenant_id: UUID, source: bytes, metadata: Any
    ) -> IngestionIdentifiers:
        assert tenant_id == TENANT
        assert source.startswith(b"# Shipping")
        assert metadata.slug == "shipping-policy"
        return IngestionIdentifiers(DOC, VERSION, JOB, IngestionJobStatus.QUEUED)

    async def get_job(self, tenant_id: UUID, job_id: UUID) -> JobView | None:
        if tenant_id != TENANT or job_id != JOB:
            return None
        return JobView(
            id=JOB,
            version_id=VERSION,
            status=IngestionJobStatus.SUCCEEDED,
            attempt_count=1,
            failure_code=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            completed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    async def activate(self, tenant_id: UUID, version_id: UUID) -> VersionMetadata:
        assert tenant_id == TENANT
        assert version_id == VERSION
        return VersionMetadata(
            id=VERSION,
            document_id=DOC,
            slug="shipping-policy",
            title="Shipping Policy",
            document_type="policy",
            language="en",
            version="2026.1",
            effective_date=date(2026, 1, 1),
            status=VersionStatus.ACTIVE,
            activated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def admin_app() -> FastAPI:
    from verbaops.api.app import create_app

    context = build_context(customer_id=None)
    context = context.model_copy(update={"roles": frozenset({Role.TENANT_ADMIN})})
    settings = cast(Callable[..., Settings], Settings)(_env_file=None)
    app = create_app(
        settings=settings,
        auth_provider=build_provider(context),
    )
    from verbaops.api.dependencies import get_knowledge_service

    app.dependency_overrides[get_knowledge_service] = lambda: FakeKnowledgeService()
    return app


@pytest.mark.asyncio
async def test_tenant_admin_upload_returns_202_and_never_accepts_tenant_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = admin_app()
    monkeypatch.setattr(
        "verbaops.api.routes.knowledge_admin.enqueue_knowledge_job",
        lambda _job_id: "celery-task-1",
    )
    response = await request(
        app,
        "POST",
        "/v1/admin/knowledge/documents",
        headers={"Authorization": "Bearer opaque-test-credential"},
        lifespan=True,
        json=None,
    )
    assert response.status_code == 422

    transport = __import__("httpx").ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        __import__("httpx").AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        response = await client.post(
            "/v1/admin/knowledge/documents",
            headers={"Authorization": "Bearer opaque-test-credential"},
            files={
                "file": (
                    "shipping-policy.md",
                    b"# Shipping\nShips in two days.",
                    "text/markdown",
                )
            },
            data={
                "slug": "shipping-policy",
                "title": "Shipping Policy",
                "document_type": "policy",
                "language": "en",
                "version": "2026.1",
                "effective_date": "2026-01-01",
                "tenant_id": str(UUID("99999999-9999-9999-9999-999999999999")),
            },
        )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert "tenant_id" not in response.json()


@pytest.mark.asyncio
async def test_customer_role_is_denied_and_job_status_is_tenant_scoped() -> None:
    from verbaops.api.app import create_app

    settings = cast(Callable[..., Settings], Settings)(_env_file=None)
    app = create_app(settings=settings, auth_provider=build_provider())
    from verbaops.api.dependencies import get_knowledge_service

    app.dependency_overrides[get_knowledge_service] = lambda: FakeKnowledgeService()
    denied = await request(
        app,
        "GET",
        f"/v1/admin/knowledge/ingestions/{JOB}",
        headers={"Authorization": "Bearer opaque-test-credential"},
    )
    assert denied.status_code == 403

    admin = admin_app()
    status = await request(
        admin,
        "GET",
        f"/v1/admin/knowledge/ingestions/{JOB}",
        headers={"Authorization": "Bearer opaque-test-credential"},
    )
    assert status.status_code == 200
    assert status.json()["status"] == "succeeded"
