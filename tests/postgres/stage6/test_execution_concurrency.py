"""Real-PostgreSQL proof of exclusive execution and reconciliation leases."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from tests.postgres.stage6.conftest import Stage6ActionContext, seed_stage6_action_context

from verbaops.actions.executor import ActionExecutor
from verbaops.actions.models import (
    ActionProposal,
    ActionState,
    CancelOrderProposal,
    SupportTicketProposal,
    TicketCategory,
)
from verbaops.actions.persistence import ActionEvent, ActionRequest
from verbaops.actions.policy import PolicyDecision
from verbaops.actions.proposals import ActionFreshnessResult
from verbaops.actions.reconciliation import ActionReconciler
from verbaops.actions.repository import ActionRepository
from verbaops.actions.transitions import (
    ActionEventType,
    ActionRequestRecord,
    ActionTransitionService,
)
from verbaops.commerce.client import CommerceWriteResult
from verbaops.commerce.models import (
    CancelOrderResponse,
    OrderResponse,
    OrderStatus,
    SupportTicketCategory,
    SupportTicketResponse,
    SupportTicketStatus,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.concurrency,
    pytest.mark.critical_race,
]

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


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


class BlockingCancelCommerce:
    def __init__(self, order_id: UUID, customer_id: UUID) -> None:
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
        self.started.set()
        await self.release.wait()
        return CommerceWriteResult(CancelOrderResponse(order=self.order, shipment=None), 200, False)

    async def get_order(self, *_args: object) -> OrderResponse:
        return self.order


class BlockingTicketCommerce:
    def __init__(self, response: SupportTicketResponse) -> None:
        self.response = response
        self.replay_calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def create_support_ticket(
        self, *_args: object
    ) -> CommerceWriteResult[SupportTicketResponse]:
        self.replay_calls += 1
        self.started.set()
        await self.release.wait()
        return CommerceWriteResult(self.response, 201, True)

    async def get_support_ticket(self, *_args: object) -> SupportTicketResponse:
        return self.response


async def _create_and_confirm(
    engine: AsyncEngine,
    *,
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
        context.trusted_context.tenant_id,
        fingerprint,
        ActionState.AWAITING_CONFIRMATION,
        None,
        ActionEventType.POLICY_ALLOWED,
        "allowed",
        policy_decision=allowed_policy(),
    )
    action = await transitions.transition(
        action.id,
        context.trusted_context.tenant_id,
        fingerprint,
        ActionState.READY_TO_EXECUTE,
        context.trusted_context.principal_id,
        ActionEventType.CUSTOMER_CONFIRMED,
        None,
    )
    return action, transitions


@pytest.mark.asyncio
async def test_two_workers_claim_one_action_and_dispatch_once(
    postgres_engine: AsyncEngine,
    clean_stage6_action_tables: None,
) -> None:
    del clean_stage6_action_tables
    context = await seed_stage6_action_context(postgres_engine)
    order_id = uuid4()
    fingerprint = "d" * 64
    action, transitions = await _create_and_confirm(
        postgres_engine,
        context=context,
        proposal=CancelOrderProposal(order_id=order_id),
        fingerprint=fingerprint,
    )
    customer_id = context.trusted_context.customer_id
    assert customer_id is not None
    commerce = BlockingCancelCommerce(order_id, customer_id)
    freshness = FixedFreshness(fingerprint)
    executors = [
        ActionExecutor(
            commerce_client=commerce,  # type: ignore[arg-type]
            transition_service=transitions,
            freshness_service=freshness,  # type: ignore[arg-type]
        )
        for _ in range(2)
    ]

    first = asyncio.create_task(executors[0].execute_ready(action.id))
    await commerce.started.wait()
    second = asyncio.create_task(executors[1].execute_ready(action.id))
    second_result = await second
    commerce.release.set()
    first_result = await first

    assert commerce.calls == 1
    assert ActionState(second_result.state) is ActionState.EXECUTING
    assert ActionState(first_result.state) is ActionState.SUCCEEDED
    async with postgres_engine.connect() as connection:
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
        stored = (
            await connection.execute(
                select(
                    ActionRequest.state,
                    ActionRequest.commerce_status_code,
                    ActionRequest.commerce_resource_id,
                    ActionRequest.verification_status,
                    ActionRequest.verified_resource_id,
                    ActionRequest.execution_lease_owner,
                ).where(ActionRequest.id == action.id)
            )
        ).one()
    assert event_types.count(ActionEventType.EXECUTION_STARTED.value) == 1
    assert event_types.count(ActionEventType.COMMERCE_RESPONSE.value) == 1
    assert event_types.count(ActionEventType.VERIFICATION_SUCCEEDED.value) == 1
    assert stored.state == ActionState.SUCCEEDED.value
    assert stored.commerce_status_code == 200
    assert stored.commerce_resource_id == order_id
    assert stored.verification_status == "verified"
    assert stored.verified_resource_id == order_id
    assert stored.execution_lease_owner is None


@pytest.mark.asyncio
async def test_two_reconciliation_workers_cannot_dispatch_separate_same_key_replays(
    postgres_engine: AsyncEngine,
    clean_stage6_action_tables: None,
) -> None:
    del clean_stage6_action_tables
    context = await seed_stage6_action_context(postgres_engine)
    fingerprint = "e" * 64
    proposal = SupportTicketProposal(
        order_id=None,
        category=TicketCategory.OTHER,
        subject="Need assistance",
        description="Please contact me",
    )
    action, transitions = await _create_and_confirm(
        postgres_engine,
        context=context,
        proposal=proposal,
        fingerprint=fingerprint,
    )
    claim = await transitions.claim_execution(
        action.id,
        action.tenant_id,
        action.proposal_fingerprint,
    )
    assert claim.claimed and claim.lease_owner is not None
    await transitions.record_execution_outcome(
        action.id,
        action.tenant_id,
        action.proposal_fingerprint,
        claim.lease_owner,
        target_state=ActionState.UNRESOLVED,
        event_type=ActionEventType.UNRESOLVED,
        reason_code="write_outcome_unknown",
        status_code=503,
        error_code="write_outcome_unknown",
        resource_id=None,
    )
    customer_id = context.trusted_context.customer_id
    assert customer_id is not None
    response = SupportTicketResponse(
        id=uuid4(),
        customer_id=customer_id,
        order_id=None,
        category=SupportTicketCategory.OTHER,
        subject=proposal.subject,
        description=proposal.description,
        status=SupportTicketStatus.OPEN,
        created_at=NOW,
        updated_at=NOW,
    )
    commerce = BlockingTicketCommerce(response)
    reconciler = ActionReconciler(
        commerce_client=commerce,  # type: ignore[arg-type]
        transition_service=transitions,
    )

    first = asyncio.create_task(reconciler.reconcile(action.id, context.trusted_context))
    await commerce.started.wait()
    second = asyncio.create_task(reconciler.reconcile(action.id, context.trusted_context))
    second_result = await second
    commerce.release.set()
    first_result = await first

    assert commerce.replay_calls == 1
    assert ActionState(second_result.state) is ActionState.UNRESOLVED
    assert ActionState(first_result.state) is ActionState.SUCCEEDED
    async with postgres_engine.connect() as connection:
        stored = (
            await connection.execute(
                select(ActionRequest.state, ActionRequest.idempotency_key).where(
                    ActionRequest.id == action.id
                )
            )
        ).one_or_none()
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
    assert stored is not None
    assert stored.state == ActionState.SUCCEEDED.value
    assert stored.idempotency_key == action.idempotency_key
    assert event_types.count(ActionEventType.UNRESOLVED.value) == 2
    assert event_types.count(ActionEventType.VERIFICATION_SUCCEEDED.value) == 1
