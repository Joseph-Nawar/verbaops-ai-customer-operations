# RelayAI Stage 1 Engineering Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the reproducible Python 3.12/uv foundation, validated configuration, trusted identity boundary, and FastAPI request infrastructure for RelayAI without implementing later Stage 1 application capabilities.

**Architecture:** M1A creates the installable `src/relayai` package and repository tooling. M1B adds validated configuration, an authentication-provider abstraction, and immutable server-derived identity context. M1C adds only the FastAPI application/request context, dependency injection, operational endpoints, and structured logging; persistence, AI, voice, and commerce behavior remain outside the active milestone.

**Tech Stack:** Python 3.12, uv, Hatchling, Pydantic, pydantic-settings, FastAPI, Starlette, httpx, pytest, pytest-asyncio, pytest-cov, Ruff, mypy, pre-commit, and GNU Make as an optional convenience wrapper.

**Spec:** Locked Phase 0 documentation at commit `1446bed` plus the M1A request.

## Global Constraints

- Python line: `3.12`.
- `requires-python = ">=3.12,<3.13"`.
- Distribution/project name: `relay-ai`.
- Import package: `relayai`.
- Use `uv` for project and dependency management and commit `uv.lock`.
- Do not add application/runtime dependencies unless strictly required to build/install the package.
- Do not add Uvicorn/Gunicorn, databases, Redis clients, Docker, LangGraph, AI/provider SDKs, RAG, voice, AWS, frontend code, NovaCommerce models, or empty future package directories.
- Do not modify locked Phase 0 product or architecture decisions.
- M1A and M1B are accepted/complete; M1C is the active milestone. M1D through M1F remain not started.

## Locked Stage 1 sequence

| Milestone | Boundary | Status |
|---|---|---|
| M1A Python Toolchain & Repository Foundation | Python/uv package, tooling, smoke test, and developer commands only | Accepted/complete |
| M1B Configuration & Trusted Identity Boundary | Configuration, authentication-provider abstraction, and immutable trusted context | Accepted/complete |
| M1C FastAPI Application & Request Infrastructure | FastAPI application, request context, dependency injection, operational routes, and structured logging | Active milestone |
| M1D Persistence & Runtime Infrastructure | Recorded boundary only; not implemented | Not started |
| M1E Engineering Automation | Recorded boundary only; not implemented | Not started |
| M1F Stage 1 Final Gate | Recorded boundary only; not implemented | Not started |

### Task 1: Package smoke behavior

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_package.py`

- [ ] Write tests proving that the installed project imports `relayai`, exposes version `0.1.0` from distribution metadata, and resolves to `src/relayai` without a repository-root package hack.
- [ ] Run the test through the uv-managed environment and confirm it fails because the package foundation does not yet exist.

### Task 2: Python/uv foundation

**Files:**
- Create: `.python-version`
- Create: `pyproject.toml`
- Create: `src/relayai/__init__.py`
- Create: `src/relayai/py.typed`
- Create: `uv.lock`

- [ ] Configure Python 3.12, project name `relay-ai`, version `0.1.0`, `src` layout, Hatchling build metadata, empty runtime dependencies, and the requested development tools.
- [ ] Implement only distribution-backed `relayai.__version__` metadata.
- [ ] Run `uv sync` to create the lockfile and environment.
- [ ] Re-run the package tests and confirm they pass.

### Task 3: Developer command interface

**Files:**
- Create: `Makefile`
- Create: `.pre-commit-config.yaml`

- [ ] Add `sync`, `lint`, `format-check`, `typecheck`, `test`, and `check` wrappers around canonical uv commands.
- [ ] Keep `make dev` and `make down` absent because the local runtime stack is not part of M1A.
- [ ] Configure Ruff, mypy, pytest/coverage, and simple pre-commit repository hygiene without adding Black, isort, or Flake8.

### Task 4: Verification and lock

**Files:**
- Modify: only M1A files if verification identifies a concrete issue.

- [ ] Run uv sync, pytest, coverage, Ruff check, Ruff format check, mypy, pre-commit, Makefile checks, Mermaid-independent repository scans, and `git diff --check`.
- [ ] Confirm no Stage 1 later-milestone files or runtime dependencies exist.
- [ ] Commit the verified milestone as `chore: establish RelayAI Python engineering foundation`.
