# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY alembic-commerce.ini ./alembic-commerce.ini
COPY commerce_migrations ./commerce_migrations

RUN uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file /tmp/requirements.txt \
    && uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python --requirement /tmp/requirements.txt \
    && uv build --wheel --out-dir /tmp/dist \
    && uv pip install --python /opt/venv/bin/python --no-deps /tmp/dist/*.whl

FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN addgroup --system verbaops \
    && adduser --system --ingroup verbaops verbaops

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/migrations /app/migrations
COPY --from=builder /app/alembic-commerce.ini /app/alembic-commerce.ini
COPY --from=builder /app/commerce_migrations /app/commerce_migrations

USER verbaops
EXPOSE 8000
CMD ["uvicorn", "verbaops.api.runtime:create_runtime_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
