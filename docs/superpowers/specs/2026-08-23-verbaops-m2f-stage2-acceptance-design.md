# VerbaOps AI M2F Stage 2 Acceptance Design

## Purpose

M2F is Stage 2 system acceptance, not new Commerce functionality. It leaves a
permanent black-box acceptance harness for Stage 3+ while treating NovaCommerce
as an external service. Stage 2 is not locked until the M2F pull-request CI and
post-merge main CI pass the permanent acceptance gate.

## Boundary

Acceptance behavior tests communicate with NovaCommerce only over HTTP. Files
under `tests/acceptance/commerce/` may not import `novacommerce`, `verbaops`,
`sqlalchemy`, `asyncpg`, or `alembic`; they use `httpx` and environment-provided
values only. They do not access a database, require a VerbaOps process, require
the VerbaOps database, or add a test-only application endpoint.

## Scope

The suite exercises all six GET and all six POST `/v1` operations, representative
authentication, trusted customer context, anti-enumeration, required
`Idempotency-Key`, identical replay, same-key request conflict, one persisted
business rejection replay, and live OpenAPI parity. It asserts exactly six GET
and six POST `/v1` operations and does not duplicate the detailed M2C/M2D race
matrix.

## Acceptance stack

`docker-compose.acceptance.yml` contains only `commerce-postgres`,
`commerce-migrate`, `commerce-seed`, `commerce-fixtures`, and `commerce-api`.
Each run uses a unique Compose project, fresh volumes, a configurable API port
(default `18010`) bound to `127.0.0.1`, a random ephemeral database password,
and a random service token. It never reads repository `.env` or `.secrets`,
prints credentials, or uses VerbaOps, Redis, or port `8010`. The orchestrator
always tears down containers, networks, and volumes, including on failure; a
teardown failure is itself a command failure.

## Canonical seed and overlay

The existing M2B seed remains unchanged: seed `20260821`, as-of `2026-08-21`,
fingerprint
`f9c5a32603d7087eb820deffcbf8fdd27324e0fbd677d3f9c4774b335aadacdb`, and
migration head `0001_create_commerce_schema`. The orchestrator parses the seed
CLI JSON and compares its scenario IDs to the committed external manifest
`tests/acceptance/fixtures/novacommerce-scenarios.json`; black-box tests do not
import seed helpers.

Because canonical August-2026 records age, a one-off fixture setup service uses
one UTC `ACCEPTANCE_AS_OF` per run to add only new acceptance-owned rows for a
recently delivered primary-customer order, a reschedulable shipment, and future
delivery slots. It never updates or deletes canonical rows, is idempotent only
within the fresh database, and uses stable manifest UUIDs.

## OpenAPI contract

The pure normalization functions move to `scripts/openapi_contract.py`.
`scripts/normalize_openapi.py` retains its existing CLI and re-exports the pure
functions. The committed OpenAPI snapshot must remain byte-identical. The live
suite downloads `/openapi.json`, applies the same normalization, compares it to
`contracts/novacommerce-openapi.json`, and rejects any `/v1` method or route
outside exactly six GET and six POST operations.

## CI and developer command

`make commerce-acceptance` is the only canonical command. The ordinary suite
excludes both `postgres` and `commerce_acceptance`. CI preserves the existing
jobs `quality`, `postgres-contract`, `postgres-concurrency`, and `docker-build`
and adds an independent `commerce-acceptance` job on pull requests and pushes
to main using pinned Ubuntu, uv `0.12.5`, project Python, `uv lock --check`,
`uv sync --locked`, and `make commerce-acceptance` with a bounded timeout.
Branch protection is not changed by M2F implementation.

## Non-goals

M2F changes no production source behavior, Commerce schema, migrations, seed
implementation/data, committed OpenAPI snapshot, API business routes, auth
rules, idempotency behavior, or Docker development stack. It does not add
Stage 3 agents, RAG, voice, or business functionality.
