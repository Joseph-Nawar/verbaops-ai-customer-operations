# VerbaOps AI

## Production-Grade Multilingual Agentic Customer Operations Platform

VerbaOps AI is a production-oriented multilingual customer-operations platform being built to demonstrate safe agentic AI, tool execution, retrieval, real-time voice, evaluation, and production infrastructure. The current repository state contains the completed Stage 1 engineering foundation; AI and business-domain functionality are introduced in later stages.

## Current status

**Stage 1 — Repository & Engineering Foundation**

Currently implemented:

- Python 3.12 and uv project management;
- FastAPI application foundation;
- trusted identity boundary;
- structured JSON logging;
- request and correlation context;
- PostgreSQL 16 with pgvector infrastructure;
- asynchronous SQLAlchemy foundation;
- Alembic migrations;
- Redis connectivity;
- Docker and Compose runtime;
- GitHub Actions CI;
- testing and static-quality gates.

Not implemented yet:

- NovaCommerce business domain;
- LLM agent or LangGraph;
- RAG and tool execution;
- deterministic policy engine;
- confirmation and human-in-the-loop workflows;
- Arabic/multilingual hardening;
- voice capabilities;
- production cloud deployment.

## Architecture principles

- The LLM is not an authorization authority.
- Identity is derived from trusted server context.
- Agents will not directly modify commerce databases.
- Deterministic policy controls protected actions.
- NovaCommerce is the sole demo tenant while the platform remains tenant-aware.
- The architecture remains modular without premature distributed deployment.

See the [requirements](docs/product/requirements.md), [system overview](docs/architecture/system-overview.md), [threat model](docs/security/threat-model.md), and [ADRs](docs/adr/) for the locked design. ADR-009 records the project identity migration.

## Prerequisites

- Git;
- Docker Desktop or Docker Engine with Compose;
- uv;
- Python 3.12;
- GNU Make (optional convenience wrapper).

uv can provision the required Python version from the repository's `.python-version` file.

## Quickstart

Install the locked development environment:

```bash
uv sync --locked
```

Run the canonical quality checks directly through uv:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

The optional Make wrapper provides:

```bash
make sync
make check
make dev
make down
make migrate
```

`make dev` creates ignored local configuration and secrets when absent, starts PostgreSQL 16 with pgvector and Redis, runs the Alembic migration, and starts the API. It generates the local database password; no password needs to be invented or copied manually.

## API operational endpoints

The current API intentionally exposes operational endpoints only:

- `GET /health` — liveness;
- `GET /ready` — PostgreSQL and Redis readiness;
- `GET /version` — service metadata;
- `GET /docs` — FastAPI documentation;
- `GET /openapi.json` — OpenAPI schema.

There are deliberately no customer, business, or AI endpoints yet.

## Local configuration

The application reads these `VERBAOPS_`-prefixed settings:

```text
VERBAOPS_ENVIRONMENT
VERBAOPS_DATABASE__URL
VERBAOPS_REDIS__URL
VERBAOPS_OBSERVABILITY__LOG_LEVEL
```

The `.env` file and `.secrets/` directory are generated local development artifacts and are ignored by Git and Docker build context. Do not commit or print their secret values.

## Quality gates

The engineering foundation enforces:

- Ruff linting;
- Ruff formatting;
- mypy type checking;
- pytest;
- at least 80% branch-aware coverage;
- pre-commit repository checks;
- Docker runtime image builds;
- GitHub Actions verification on pull requests and pushes to `main`.

## Documentation

- [Product requirements](docs/product/)
- [Architecture](docs/architecture/)
- [Security](docs/security/)
- [Evaluation](docs/evaluation/)
- [Architecture decision records](docs/adr/)
