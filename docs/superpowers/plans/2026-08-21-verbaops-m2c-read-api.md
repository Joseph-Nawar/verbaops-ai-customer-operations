# M2C Execution Plan — Authenticated NovaCommerce Read API

Status: M2A complete; M2B complete; M2C active; M2D–M2F not started.

## 1. Baseline and documentation

- Confirm synchronized main at the locked M2B merge SHA.
- Create `stage2/m2c-authenticated-read-api` from main.
- Record and review the approved M2C design and this plan.

## 2. Contract-first tests

- Add settings/bootstrap tests for token validation, preservation, generation,
  and fail-closed runtime behavior.
- Add auth/context/error/schema tests for the exact envelopes, headers,
  constant-time comparison, Decimal serialization, and OpenAPI scheme.
- Add pure search and delivery-clock tests, including wildcard escaping and date
  range validation.
- Add read-only route shape and architecture tests before implementation.
- Run focused tests before implementation to capture genuine RED results.

## 3. Read-only implementation

- Add the service-token setting and additive development bootstrap behavior.
- Add immutable trusted customer context and bearer/customer dependencies.
- Add safe API errors and focused Pydantic response schemas.
- Add focused SQLAlchemy services and six GET-only `/v1` routers.
- Compose the routers with existing operational routes without changing M2A/M2B
  persistence or migration behavior.
- Run focused tests to GREEN and keep the routes thin.

## 4. PostgreSQL contract verification

- Add integration tests using the M2B seed scenario API, never copied UUIDs.
- Run them against disposable PostgreSQL 16 after migration and canonical seed.
- Verify ownership anti-enumeration, product search, slot derivation,
  authentication, Decimal values, and before/after read-only counts.
- Verify migration head and an empty migration diff.

## 5. Acceptance and handoff

- Run the full lint/type/test/coverage/pre-commit/Compose/Docker regression.
- Run live Compose HTTP acceptance and clean up disposable containers/volumes.
- Confirm canonical M2B fingerprint is unchanged and no M2D scope entered.
- Commit exactly `feat: add authenticated NovaCommerce read API`, push the branch,
  open the requested draft PR, and wait for hosted `quality` and `docker-build`
  success on the exact head SHA.
- Keep M2C active until the technical-lead packet is complete; do not merge or
  begin M2D.
