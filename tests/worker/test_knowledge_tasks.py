from uuid import UUID

import pytest

from verbaops.knowledge.tasks import enqueue_knowledge_job, ingest_knowledge_job


def test_knowledge_task_uses_postgres_job_id_as_transport_identity() -> None:
    assert ingest_knowledge_job.name == "verbaops.knowledge.ingest"
    assert ingest_knowledge_job.app.conf.result_backend is None


def test_enqueue_returns_celery_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        id = "celery-task-id"

    monkeypatch.setattr(ingest_knowledge_job, "delay", lambda value: Result())

    assert enqueue_knowledge_job(UUID("40000000-0000-0000-0000-000000000003")) == "celery-task-id"
