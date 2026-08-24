# VerbaOps AI

## Production-Grade Multilingual Agentic Customer Operations Platform

VerbaOps AI is a production-oriented multilingual customer-operations platform being built to demonstrate safe agentic AI, tool execution, retrieval, real-time voice, evaluation, and production infrastructure. The repository currently contains the completed Stage 1 foundation and Stage 2 NovaCommerce persistence, seed, authenticated API, transactional-write, hosted-contract, and permanent black-box acceptance milestones.

## Current status

**Stage 1 — Repository & Engineering Foundation**

Currently implemented:

- isolated NovaCommerce PostgreSQL persistence and service boundary;
- deterministic fictional seed dataset (`20260821`, `2026-08-21`);
- authenticated read and transactional write HTTP APIs;
- PostgreSQL idempotency, concurrency, and hosted-contract gates;
- permanent black-box Commerce acceptance gate;
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

**Stage 3 â€” Read-Only Text Agent and Web Chat**

Currently implemented:

- a separate HTTP-only LiteLLM gateway;
- a first LangGraph read-only text agent;
- exactly five typed READ_ONLY NovaCommerce tools;
- durable conversations, messages, model calls, and tool traces;
- authenticated conversation HTTP API;
- a minimal Next.js browser chat through a server-only BFF.

The Stage 3 agent is intentionally read-only. The future roadmap, outside this
stage, may consider RAG, embeddings, Arabic specialization, voice, write or
mutation workflows, HITL, multi-agent behavior, streaming UI, and production
identity-provider integration.

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
- Node.js 24 LTS and pnpm 11.23.0 for the web app;
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
make web-check
make web-smoke
```

### Local web chat

The web app lives in `apps/web` and calls only same-origin BFF routes. To run
it locally, install the locked dependencies, copy the example environment,
set the server-only VerbaOps API URL and bearer token, then start Next.js:

```bash
corepack pnpm --dir apps/web install --frozen-lockfile
cp apps/web/.env.local.example apps/web/.env.local
# edit apps/web/.env.local with the development API token
corepack pnpm --dir apps/web dev
```

The bearer token is never exposed to browser JavaScript or `NEXT_PUBLIC_*`
configuration.

`make dev` creates ignored local configuration and secrets when absent, starts PostgreSQL 16 with pgvector and Redis, runs the Alembic migration, and starts the API. It generates the local database password; no password needs to be invented or copied manually.

## API operational endpoints

The current API intentionally exposes operational endpoints only:

- `GET /health` — liveness;
- `GET /ready` — PostgreSQL and Redis readiness;
- `GET /version` — service metadata;
- `GET /docs` — FastAPI documentation;
- `GET /openapi.json` — OpenAPI schema.

NovaCommerce exposes the locked Stage 2 HTTP contract. VerbaOps still has no
direct Commerce database access; later AI capabilities are intentionally out
of scope for this repository state.

The authenticated conversation API also exposes:

- `POST /v1/conversations` to create a trusted conversation;
- `POST /v1/conversations/{conversation_id}/messages` to run one read-only
  agent turn;
- `GET /v1/conversations/{conversation_id}` for customer-visible history.

NovaCommerce remains behind the typed read client; VerbaOps does not directly
access the Commerce database.

## Permanent Commerce acceptance

Run the disposable black-box gate with:

```bash
make commerce-acceptance
```

The command creates a unique Compose project with five services:
`commerce-postgres`, `commerce-migrate`, `commerce-seed`, `commerce-fixtures`,
and `commerce-api`. It generates ephemeral credentials, uses only HTTP from
the acceptance tests, compares the canonical seed result with the external
scenario manifest, applies a setup-only time-relative fixture overlay, and
removes containers, networks, and volumes on every exit. The API is bound to
`127.0.0.1:18010` by default; set `ACCEPTANCE_API_PORT` to override it.

The acceptance command does not read repository `.env` or `.secrets` files
and does not create them. Its independent CI gate is named
`commerce-acceptance`, alongside `quality`, `postgres-contract`,
`postgres-concurrency`, and `docker-build`.

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
- web linting, strict TypeScript, Vitest, Next.js production builds, and the
  deterministic Playwright browser smoke test;
- GitHub Actions verification on pull requests and pushes to `main`.

## Documentation

- [Product requirements](docs/product/)
- [Architecture](docs/architecture/)
- [Security](docs/security/)
- [Evaluation](docs/evaluation/)
- [Architecture decision records](docs/adr/)
