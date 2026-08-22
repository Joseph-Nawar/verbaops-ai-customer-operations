"""PostgreSQL-backed idempotent write execution."""

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from novacommerce.api.errors import APIError
from novacommerce.db.models.idempotency import IdempotencyRecord, IdempotencyStatus

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,255}$")


def validate_idempotency_key(value: str | None) -> str:
    """Validate the semantic idempotency header before opening persistence."""

    if value is None or value == "":
        raise APIError(400, "idempotency_key_required", "Idempotency-Key is required.")
    if not _KEY_PATTERN.fullmatch(value):
        raise APIError(422, "invalid_idempotency_key", "Idempotency-Key is invalid.")
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, ".2f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if hasattr(value, "model_dump"):
        return _json_value(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def request_fingerprint(
    operation: str,
    customer_id: UUID,
    *,
    target_ids: tuple[UUID, ...] = (),
    body: Any = None,
) -> str:
    """Hash the stable operation identity, trusted customer, targets, and body."""

    envelope = {
        "operation": operation,
        "customer_id": str(customer_id),
        "target_ids": [str(target) for target in target_ids],
        "body": _json_value(body),
    }
    canonical = json.dumps(envelope, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    """Authoritative response data produced inside the write transaction."""

    status_code: int
    body: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WriteExecution:
    """HTTP response data including whether the result was replayed."""

    outcome: WriteOutcome
    replayed: bool = False


def _json_safe_body(body: Mapping[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], _json_value(dict(body)))


async def execute_idempotent_write(
    session: AsyncSession,
    *,
    key: str,
    operation: str,
    customer_id: UUID,
    fingerprint: str,
    operation_fn: Callable[[AsyncSession], Awaitable[WriteOutcome]],
    commit_fn: Callable[[], Awaitable[None]] | None = None,
) -> WriteExecution:
    """Own the complete idempotency transaction and commit exactly once."""

    await session.begin()
    try:
        inserted = await session.execute(
            insert(IdempotencyRecord)
            .values(
                key=key,
                operation=operation,
                customer_id=customer_id,
                request_fingerprint=fingerprint,
                status=IdempotencyStatus.IN_PROGRESS,
                created_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=[IdempotencyRecord.key])
            .returning(IdempotencyRecord.key)
        )
        is_new = inserted.scalar_one_or_none() is not None
        if not is_new:
            existing = (
                await session.execute(
                    select(IdempotencyRecord).where(IdempotencyRecord.key == key).with_for_update()
                )
            ).scalar_one()
            if (
                existing.operation != operation
                or existing.customer_id != customer_id
                or existing.request_fingerprint != fingerprint
            ):
                raise APIError(
                    409,
                    "idempotency_key_reused",
                    "Idempotency-Key was already used for a different request.",
                )
            if existing.status != IdempotencyStatus.COMPLETED or existing.response_body is None:
                raise APIError(
                    503,
                    "write_outcome_unknown",
                    "The operation outcome could not be confirmed. Retry using the same idempotency key.",
                )
            outcome = WriteOutcome(
                status_code=existing.response_status or 500,
                body=dict(existing.response_body),
            )
            await session.rollback()
            return WriteExecution(outcome=outcome, replayed=True)

        outcome = await operation_fn(session)
        body = _json_safe_body(outcome.body)
        await session.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.key == key)
            .values(
                status=IdempotencyStatus.COMPLETED,
                response_status=outcome.status_code,
                response_body=body,
                completed_at=datetime.now(UTC),
            )
        )
        if commit_fn is None:
            await session.commit()
        else:
            await commit_fn()
        return WriteExecution(outcome=WriteOutcome(outcome.status_code, body))
    except APIError:
        await session.rollback()
        raise
    except Exception as error:
        await session.rollback()
        raise APIError(
            503,
            "write_outcome_unknown",
            "The operation outcome could not be confirmed. Retry using the same idempotency key.",
        ) from error


def write_response(execution: WriteExecution) -> JSONResponse:
    """Turn an executor result into the exact API response and replay header."""

    headers = {"X-Idempotent-Replay": "true"} if execution.replayed else {}
    return JSONResponse(
        status_code=execution.outcome.status_code,
        content=execution.outcome.body,
        headers=headers,
    )
