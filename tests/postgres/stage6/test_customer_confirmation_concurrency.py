"""PostgreSQL confirmation commit and concurrent-confirmation dispatch boundary."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from tests.postgres.stage6.conftest import Stage6ActionContext, seed_stage6_action_context

from verbaops.actions.decisions import ActionDecisionService
from verbaops.actions.executor import ActionExecutor
from verbaops.actions.models import ActionProposal, ActionState, CancelOrderProposal
from verbaops.actions.persistence import ActionEvent, ActionRequest
from verbaops.actions.policy import PolicyDecision
from verbaops.actions.proposals import ActionFreshnessResult
from verbaops.actions.repository import ActionRepository
from verbaops.actions.transitions import (
    ActionEventType,
    ActionRequestRecord,
    ActionTransitionService,
)
from verbaops.commerce.client import CommerceWriteResult
from verbaops.commerce.models import CancelOrderResponse, OrderResponse, OrderStatus

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.concurrency,
    pytest.mark.critical_race,
]

NOW = datetime.now(UTC)


def allowed_policy() -> PolicyDecision:
    return PolicyDecision(
        allowed=True,
        reason_code="allowed",
        confirmation_required=True,
        approval_required=False,
        policy_version="stage6-policy-v1",
    )


class FixedFreshness:
    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint

    async def refresh(self, _record: object) -> ActionFreshnessResult:
        return ActionFreshnessResult(
            proposal_fingerprint=self.fingerprint,
            policy_decision=allowed_policy(),
            canonical_currency="USD",
        )


class CommitObservingCommerce:
    def __init__(
        self, engine: AsyncEngine, action_id: UUID, order_id: UUID, customer_id: UUID
    ) -> None:
        self.engine = engine
        self.action_id = action_id
        self.order_id = order_id
        self.customer_id = customer_id
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.order = OrderResponse(
            id=order_id,
            customer_id=customer_id,
            status=OrderStatus.CANCELLED,
            total="50.00",
            created_at=NOW,
            updated_at=NOW,
            items=[],
        )

    async def cancel_order(self, *_args: object) -> CommerceWriteResult[CancelOrderResponse]:
        self.calls += 1
        async with self.engine.connect() as connection:
            committed_state = (
                await connection.execute(
                    select(
                        ActionRequest.state,
                        ActionRequest.customer_confirmation_decision,
                    ).where(ActionRequest.id == self.action_id)
                )
            ).one()
            confirmation_event = await connection.scalar(
                select(ActionEvent.id).where(
                    ActionEvent.action_request_id == self.action_id,
                    ActionEvent.event_type == ActionEventType.CUSTOMER_CONFIRMED.value,
                )
            )
        assert committed_state.state == ActionState.EXECUTING.value
        assert committed_state.customer_confirmation_decision == "confirmed"
        assert confirmation_event is not None
        self.started.set()
        await self.release.wait()
        return CommerceWriteResult(CancelOrderResponse(order=self.order, shipment=None), 200, False)

    async def get_order(self, *_args: object) -> OrderResponse:
        return self.order


async def _create_pending_action(
    engine: AsyncEngine,
    context: Stage6ActionContext,
    proposal: ActionProposal,
    fingerprint: str,
) -> tuple[ActionRequestRecord, ActionTransitionService]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repository = ActionRepository(factory)
    transitions = ActionTransitionService(factory)
    action, _created = await repository.create_or_get(
        trusted_context=context.trusted_context,
        conversation_id=context.conversation_id,
        agent_run_id=context.agent_run_id,
        tool_invocation_id=context.tool_invocation_ids[0],
        proposal=proposal,
        proposal_fingerprint=fingerprint,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    await transitions.transition(
        action.id,
        action.tenant_id,
        fingerprint,
        ActionState.AWAITING_CONFIRMATION,
        None,
        ActionEventType.POLICY_ALLOWED,
        "allowed",
        policy_decision=allowed_policy(),
    )
    return action, transitions


@pytest.mark.asyncio
async def test_concurrent_confirmation_commits_decision_before_one_write_dispatch(
    postgres_engine: AsyncEngine,
    clean_stage6_action_tables: None,
) -> None:
    del clean_stage6_action_tables
    context = await seed_stage6_action_context(postgres_engine)
    fingerprint = "f" * 64
    order_id = uuid4()
    action, transitions = await _create_pending_action(
        postgres_engine,
        context,
        CancelOrderProposal(order_id=order_id),
        fingerprint,
    )
    customer_id = context.trusted_context.customer_id
    assert customer_id is not None
    commerce = CommitObservingCommerce(postgres_engine, action.id, order_id, customer_id)
    freshness = FixedFreshness(fingerprint)
    executor = ActionExecutor(
        commerce_client=commerce,  # type: ignore[arg-type]
        transition_service=transitions,
        freshness_service=freshness,  # type: ignore[arg-type]
    )
    decisions = ActionDecisionService(
        transition_service=transitions,
        freshness_service=freshness,  # type: ignore[arg-type]
        action_executor=executor,
    )

    first = asyncio.create_task(decisions.confirm(action.id, context.trusted_context, fingerprint))
    started = asyncio.create_task(commerce.started.wait())
    done, _pending = await asyncio.wait(
        {first, started}, timeout=10, return_when=asyncio.FIRST_COMPLETED
    )
    if first in done:
        await first
    assert started in done, "confirmed action did not reach the Commerce dispatch boundary"
    second = asyncio.create_task(decisions.confirm(action.id, context.trusted_context, fingerprint))
    second_view = await second
    commerce.release.set()
    first_view = await first

    assert commerce.calls == 1
    assert first_view.state is ActionState.SUCCEEDED
    assert second_view.state in {ActionState.EXECUTING, ActionState.SUCCEEDED}
    async with postgres_engine.connect() as connection:
        stored = (
            await connection.execute(
                select(
                    ActionRequest.state,
                    ActionRequest.customer_confirmation_decision,
                    ActionRequest.customer_confirmation_fingerprint,
                ).where(ActionRequest.id == action.id)
            )
        ).one()
        event_types = (
            (
                await connection.execute(
                    select(ActionEvent.event_type)
                    .where(ActionEvent.action_request_id == action.id)
                    .order_by(ActionEvent.sequence)
                )
            )
            .scalars()
            .all()
        )
    assert stored.state == ActionState.SUCCEEDED.value
    assert stored.customer_confirmation_decision == "confirmed"
    assert stored.customer_confirmation_fingerprint == fingerprint
    assert event_types.count(ActionEventType.CUSTOMER_CONFIRMED.value) == 1
    assert event_types.count(ActionEventType.EXECUTION_STARTED.value) == 1
