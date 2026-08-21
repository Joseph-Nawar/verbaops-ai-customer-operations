# VerbaOps AI Stage 1 Engineering Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the reproducible Python 3.12/uv foundation, validated configuration, trusted identity boundary, FastAPI request infrastructure, local persistence/runtime foundation, and deterministic CI quality/build gate for VerbaOps AI without implementing later-stage application capabilities.

**Architecture:** M1A creates the installable `src/verbaops` package and repository tooling. M1B adds validated configuration, an authentication-provider abstraction, and immutable server-derived identity context. M1C adds the FastAPI application/request context, dependency injection, operational endpoints, and structured logging. M1D adds only application-owned async PostgreSQL/Redis resource lifecycles, Alembic extension setup, and local Docker composition. M1E adds deterministic GitHub Actions quality gates and a local runtime image build; persistence models, AI, voice, commerce behavior, and deployment remain outside the active milestone.

**Tech Stack:** Python 3.12, uv, Hatchling, Pydantic, pydantic-settings, FastAPI, Starlette, SQLAlchemy async, asyncpg, Alembic, redis-py asyncio, Uvicorn, Docker Compose, GitHub Actions, httpx, pytest, pytest-asyncio, pytest-cov, Ruff, mypy, pre-commit, and GNU Make as an optional convenience wrapper.

**Spec:** Locked Phase 0 architecture at commit `1446bed` plus the M1A–M1E milestone requests.

## Global Constraints

- Python line: `3.12`.
- `requires-python = ">=3.12,<3.13"`.
- Distribution/project name: `verbaops-ai`.
- Import package: `verbaops`.
- Use `uv` for project and dependency management and commit `uv.lock`.
- Do not add application/runtime dependencies unless strictly required to build/install the package.
- Do not add domain tables, NovaCommerce models, LangGraph, AI/provider SDKs, RAG, voice, AWS/cloud infrastructure, frontend code, worker services, or later-stage automation.
- Do not modify locked Phase 0 product or architecture decisions.
- M1A, M1B, M1C, M1D, and M1E are accepted/complete; M1F remains not started.

## Locked Stage 1 sequence

| Milestone | Boundary | Status |
|---|---|---|
| M1A Python Toolchain & Repository Foundation | Python/uv package, tooling, smoke test, and developer commands only | Accepted/complete |
| M1B Configuration & Trusted Identity Boundary | Configuration, authentication-provider abstraction, and immutable trusted context | Accepted/complete |
| M1C FastAPI Application & Request Infrastructure | FastAPI application, request context, dependency injection, operational routes, and structured logging | Accepted/complete |
| M1D Persistence & Runtime Infrastructure | Async SQLAlchemy/asyncpg resources, Redis lifecycle, Alembic pgvector extension migration, real readiness, Uvicorn composition, and local Docker stack; no domain tables | Accepted/complete |
| M1E Engineering Automation | Deterministic locked quality gates, coverage enforcement, pinned GitHub Actions, and local runtime image build; no publishing or deployment | Accepted/complete |
| M1F Stage 1 Final Gate | Recorded boundary only; not implemented | Not started |

### Accepted milestone record

- [x] M1A Python/uv foundation, installable package, tooling, smoke test, and developer commands accepted at `4654700`.
- [x] M1B configuration, authentication-provider abstraction, and immutable trusted context accepted at `0206840`.
- [x] M1C FastAPI request infrastructure, operational routes, dependency injection, and structured logging accepted at `e39168f`.
- [x] M1D persistence/runtime foundation, local Compose stack, and extension-only migration accepted at `5861402`.\n- [x] M1E deterministic CI quality gates, coverage enforcement, and runtime image build accepted at `a7e5367`.

### Accepted M1D boundary

- [x] Add only application-owned async SQLAlchemy/asyncpg and Redis resources, without domain models or tables.
- [x] Own resources through FastAPI lifespan with controlled readiness checks and cleanup, without automatic migrations at startup.
- [x] Add an extension-only Alembic migration enabling pgvector, plus Uvicorn factory composition and the local four-service Docker Compose stack.
- [x] Add ignored local secret bootstrap and `make dev`, `make down`, and `make migrate`; keep static/test checks independent of Docker.
- [x] Verify the disposable local stack, migration reversibility, PostgreSQL 16/vector, Redis, secret hygiene, and the complete static/test suite.

### Accepted M1E boundary

- [x] Enforce the existing deterministic-core coverage target at 80% without excluding ordinary production modules.
- [x] Add a read-only, secret-free GitHub Actions quality job with locked uv synchronization, visible Ruff, mypy, pytest/coverage, and pre-commit steps.
- [x] Add a separate quality-gated local Docker runtime build with no registry login, push, Compose startup, or deployment behavior.
- [x] Verify the workflow contract locally and preserve all developer Makefile commands.

### Future milestone boundaries

- [ ] M1F Stage 1 Final Gate remains not started and retains its existing boundary.
