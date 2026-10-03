"""Narrow async-session doubles for provider-free action repository unit tests."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from verbaops.actions.models import ActionState, CancelOrderProposal
from verbaops.actions.persistence import ActionEvent, ActionRequest
from verbaops.auth.context import Role, TrustedContext


class FakeResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value


class FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class FakeTransaction:
    async def __aenter__(self) -> FakeTransaction:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakeActionSession:
    def __init__(
        self,
        *,
        scalar_values: list[Any] | None = None,
        scalar_rows: list[list[Any]] | None = None,
        fail_flush_at: int | None = None,
        record: ActionRequest | None = None,
    ) -> None:
        self.scalar_values = deque(scalar_values or [])
        self.scalar_rows = deque(scalar_rows or [])
        self.fail_flush_at = fail_flush_at
        self.record = record
        self.added: list[ActionRequest | ActionEvent] = []
        self.flush_count = 0

    async def __aenter__(self) -> FakeActionSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> FakeTransaction:
        return FakeTransaction()

    async def scalar(self, _statement: Any) -> Any:
        if not self.scalar_values:
            raise AssertionError("unexpected scalar query")
        return self.scalar_values.popleft()

    async def scalars(self, _statement: Any) -> FakeScalars:
        if not self.scalar_rows:
            raise AssertionError("unexpected scalar rows query")
        return FakeScalars(self.scalar_rows.popleft())

    async def execute(self, statement: Any) -> FakeResult:
        values = getattr(statement, "_values", {})
        for column, expression in values.items():
            key = getattr(column, "key", column)
            value = getattr(expression, "value", expression)
            if self.record is not None:
                setattr(self.record, str(key), value)
        return FakeResult(self.record.id if self.record is not None else None)

    def add(self, entity: ActionRequest | ActionEvent) -> None:
        self.added.append(entity)
        if isinstance(entity, ActionRequest):
            self.record = entity

    async def flush(self) -> None:
        self.flush_count += 1
        if self.flush_count == self.fail_flush_at:
            raise IntegrityError("insert", {}, RuntimeError("unique conflict"))

    async def refresh(self, record: ActionRequest) -> None:
        now = datetime.now(UTC)
        if record.created_at is None:
            record.created_at = now
        if record.updated_at is None:
            record.updated_at = now
        if record.version is None:
            record.version = 1
        if record.execution_attempt_count is None:
            record.execution_attempt_count = 0
        if record.confirmation_required is None:
            record.confirmation_required = False
        if record.approval_required is None:
            record.approval_required = False


class FakeSessionFactory:
    def __init__(self, *sessions: FakeActionSession) -> None:
        self.sessions = deque(sessions)

    def __call__(self) -> FakeActionSession:
        if not self.sessions:
            raise AssertionError("unexpected session request")
        return self.sessions.popleft()


def action_context() -> TrustedContext:
    return TrustedContext(
        principal_id=uuid4(),
        tenant_id=uuid4(),
        customer_id=uuid4(),
        roles=frozenset({Role.CUSTOMER}),
    )


def action_request(
    *,
    trusted_context: TrustedContext | None = None,
    conversation_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    tool_invocation_id: UUID | None = None,
    order_id: UUID | None = None,
    proposal_fingerprint: str = "a" * 64,
    state: ActionState = ActionState.PROPOSED,
    expires_at: datetime | None = None,
    confirmation_required: bool = False,
    approval_required: bool = False,
) -> ActionRequest:
    context = trusted_context or action_context()
    order = order_id or uuid4()
    now = datetime.now(UTC)
    proposal = CancelOrderProposal(order_id=order)
    return ActionRequest(
        id=uuid4(),
        tenant_id=context.tenant_id,
        customer_id=context.customer_id,
        proposing_principal_id=context.principal_id,
        conversation_id=conversation_id or uuid4(),
        agent_run_id=agent_run_id or uuid4(),
        originating_tool_invocation_id=tool_invocation_id or uuid4(),
        action_type="cancel_order",
        proposal_payload=proposal.model_dump(mode="json"),
        target_ids=[str(order)],
        proposal_schema_version="action-proposal-v1",
        proposal_fingerprint=proposal_fingerprint,
        state=state.value,
        confirmation_required=confirmation_required,
        approval_required=approval_required,
        idempotency_key=uuid4(),
        expires_at=expires_at or now + timedelta(hours=24),
        execution_attempt_count=0,
        version=1,
        created_at=now,
        updated_at=now,
    )
