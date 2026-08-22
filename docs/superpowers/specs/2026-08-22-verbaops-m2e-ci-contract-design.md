# VerbaOps AI M2E — Hosted PostgreSQL and API Contract Design

## Status

- M2A: complete
- M2B: complete
- M2C: complete
- M2D: complete
- M2E: active
- M2F: not started

## Goal

M2E adds deterministic test taxonomy, a normalized NovaCommerce OpenAPI contract gate, local PostgreSQL parity commands, and hosted PostgreSQL CI checks without changing production source, database schema, or business behavior.

## Scope and invariants

The accepted base is `ec4dcb12c9cd14f423487b8f47a3aef691b5cf9c`. The expected M2E production-source diff is empty. The Commerce migration remains `0001_create_commerce_schema`. The locked M2B identity remains seed `20260821`, `as_of` `2026-08-21`, and fingerprint `f9c5a32603d7087eb820deffcbf8fdd27324e0fbd677d3f9c4774b335aadacdb`.

M2E does not add routes, alter request/response schemas, change persistence, modify idempotency or transaction behavior, or begin M2F.

## Marker taxonomy

Pytest registers `postgres`, `contract`, `concurrency`, and `critical_race` explicitly. Every real PostgreSQL test is discovered through the shared PostgreSQL integration location and receives `postgres` plus exactly one of `contract` or `concurrency`. `critical_race` is orthogonal but requires `postgres` and `concurrency`.

The authoritative selections are:

```text
pytest -m "postgres and contract"
pytest -m "postgres and concurrency"
pytest -m "postgres and concurrency and critical_race"
```

A collection-time validator rejects unclassified PostgreSQL integration tests, dual contract/concurrency classification, and invalid critical-race combinations. The six initial critical races are concurrent same-key execution, final inventory, double cancellation, final slot capacity, final returnable quantity, and refund balance.

## Database isolation

Each hosted PostgreSQL job owns one PostgreSQL 16 service container. Migrations run once during job setup. Shared fixtures reset NovaCommerce application tables between tests while preserving `alembic_version`; tests that need seeded data call the existing seed service explicitly with canonical `SeedConfig` values. Empty-database tests do not receive automatic seed data.

The normal local test path uses `pytest -m "not postgres"`, so `make check` remains database-independent while still running marker metadata validation.

## OpenAPI contract artifact

`contracts/novacommerce-openapi.json` is generated from the actual FastAPI application by `scripts/normalize_openapi.py`. The normalizer filters to `/v1` operations, preserves methods, parameters, request and response schemas, security requirements, validation constraints, enums, formats, and recursively referenced component closure, and removes only documented cosmetic metadata. It emits UTF-8 JSON with sorted keys, stable indentation, and a terminal newline.

`make commerce-contract-check` generates in memory/temp storage and compares bytes without modifying the committed artifact. `make commerce-contract-update` deliberately regenerates the artifact. CI invokes only the check target.

The reviewed contract contains exactly twelve business operations: six GET and six POST routes. Operational routes are excluded from the snapshot.

## Hosted CI topology

The existing `quality` and `docker-build` checks remain unchanged in name. Two jobs are added:

- `postgres-contract`: one PostgreSQL 16 service, migrations, marker validation, and one `postgres and contract` pass.
- `postgres-concurrency`: an independent PostgreSQL 16 service, migrations, one full `postgres and concurrency` pass, then two additional `postgres and concurrency and critical_race` passes.

Test failures are never retried or hidden. There is no `pytest-rerunfailures`, retry command, `continue-on-error`, shell failure suppression, or automatic application transaction retry. Health polling is limited to service readiness only.

## Branch protection

Protection is inspected before modification and only configured after the exact four M2E checks have appeared and passed on the draft PR head. Main requires pull requests, strict/up-to-date branches, and exactly these status contexts: `quality`, `postgres-contract`, `postgres-concurrency`, and `docker-build`. No review, CODEOWNERS, signed-commit, deployment-approval, or administrator-lockout requirement is added.
