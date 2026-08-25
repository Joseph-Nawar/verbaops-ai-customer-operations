"""Celery application using Redis only as an ingestion transport."""

from celery import Celery  # type: ignore[import-untyped]

from verbaops.config.settings import Settings


def create_celery_app(broker_url: str | None = None) -> Celery:
    """Build a worker app without making Redis the source of truth."""

    configured = broker_url
    if configured is None:
        settings = Settings()
        configured = (
            settings.redis.url.get_secret_value()
            if settings.redis.url is not None
            else "redis://localhost:6379/0"
        )
    return Celery(
        "verbaops",
        broker=configured,
        result_backend=None,
        include=["verbaops.knowledge.tasks"],
    )


celery_app = create_celery_app()
