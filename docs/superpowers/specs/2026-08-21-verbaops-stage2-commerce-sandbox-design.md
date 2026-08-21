# VerbaOps Stage 2 Commerce Sandbox Design

Status: approved for M2A implementation

- NovaCommerce is a separate external-style service, packaged and run independently from VerbaOps.
- `novacommerce` is a separate Python package/process with its own PostgreSQL 16 database and credentials.
- VerbaOps and NovaCommerce do not import one another; future communication is authenticated HTTP only.
- The `/v1` business API begins in M2C. Customer ownership mismatch will later use non-enumerating 404 semantics.
- Future writes use PostgreSQL-backed idempotency and commerce events; M2A only establishes their persistence schema.
- M2A establishes domain models, migrations, resources, operational service endpoints, and local stack isolation.
- M2B through M2F remain bounded future milestones: operational domain behavior, authenticated business API, customer context, write/idempotency/event workflows, and later policy/AI integrations. M2A does not pre-implement those contracts.
- There is no AI/direct Commerce DB access. VerbaOps must use the future authenticated Commerce API boundary.

Stage status: Stage 1 accepted/locked; M2A active; M2B–M2F not started.
