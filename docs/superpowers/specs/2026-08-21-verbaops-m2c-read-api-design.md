# VerbaOps AI M2C — Authenticated Read-Only NovaCommerce API

Status: approved design, M2C active

## Scope

M2C exposes a small authenticated, read-only HTTP boundary for the existing
NovaCommerce PostgreSQL schema. NovaCommerce remains an external-style service:
VerbaOps communicates with it through HTTP, and neither production package may
import the other. M2A and M2B behavior, the migration head
`0001_create_commerce_schema`, and the canonical M2B dataset remain locked.

## Authentication and trust

`NOVACOMMERCE_SERVICE_TOKEN` is an optional `SecretStr` setting for pure settings
construction, but the runtime app refuses to start without a valid token. Tokens
must be at least 32 characters; staging and production require a non-blank valid
token. `/v1` uses a named FastAPI HTTP bearer scheme with `auto_error=False` and
constant-time comparison. Missing, malformed, and incorrect credentials share one
401 response and never echo secrets.

Customer-owned reads require a UUID `X-VerbaOps-Customer-ID` header after service
authentication. The immutable trusted context is created only by the authenticated
dependency. Product and delivery-slot reads require service authentication but no
customer context.

## API contract

The six business operations are GET-only:

- `GET /v1/customers/{customer_id}`
- `GET /v1/orders/{order_id}`
- `GET /v1/orders/{order_id}/shipment`
- `GET /v1/orders/{order_id}/refunds`
- `GET /v1/products/search`
- `GET /v1/delivery-slots`

Errors use one safe `{ "error": { "code": ..., "message": ... } }` envelope.
Ownership queries constrain the trusted customer in SQL and intentionally return
the same 404 resource contract for missing and foreign-owned resources.

Money remains `Decimal` internally and serializes as decimal strings. Order item
`line_total`, and delivery-slot `remaining_capacity`/`available`, are derived
response values. Search uses escaped, parameterized PostgreSQL case-insensitive
matching over active products, deterministic ordering, and limit-plus-one
pagination. Delivery dates use an injectable UTC clock and a maximum 31-day range.

## Operations and compatibility

Health, readiness, version, docs, and OpenAPI remain unauthenticated. The
development bootstrap adds a cryptographically random token only when upgrading
a valid pre-M2C environment without one, preserves valid existing tokens, rejects
blank or malformed values, and never prints the token. The normal API runtime has
no Faker dependency; the seed image remains the only seed tooling image.

No database migration, write route, write workflow, service authentication server,
VerbaOps Commerce client, AI/RAG/voice behavior, or M2D functionality is included.

## Verification gates

TDD covers auth, trusted context, safe errors, schemas, search escaping,
pagination, fixed-clock delivery ranges, OpenAPI read-only shape, and architecture
isolation. Real PostgreSQL 16 tests use M2B's public scenario helpers and prove
anti-enumeration, canonical product/slot semantics, Decimal responses, and no
database mutation before/after the read suite. Full lint, type, test, coverage,
pre-commit, Compose, Docker, migration, and hosted CI checks are required before
the M2C draft PR is handed to technical-lead review.
