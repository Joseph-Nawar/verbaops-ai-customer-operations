"""PostgreSQL serialization of supervisor decisions and customer withdrawal."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from tests.postgres.stage6.conftest import Stage6ActionContext, seed_stage6_action_context

from verbaops.actions.decisions import ActionDecisionConflictError, ActionDecisionService
from verbaops.actions.models import ActionState, CancelOrderProposal
from verbaops.actions.persistence import ActionEvent, ActionRequest
from verbaops.actions.policy import PolicyDecision
from verbaops.actions.proposals import ActionFreshnessResult
from verbaops.actions.repository import ActionRepository
from verbaops.actions.transitions import ActionEventType, ActionTransitionService
from verbaops.auth.context import Role, TrustedContext

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.concurrency,
    pytest.mark.critical_race,
]


def approval_policy() -> PolicyDecision:
    return PolicyDecision(
        allowed=True,
        reason_code="allowed",
        confirmation_required=True,
        approval_required=True,
        policy_version="stage6-policy-v1",
    )


class FixedApprovalFreshness:
    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint

    async def refresh(self, _record: object) -> ActionFreshnessResult:
        return ActionFreshnessResult(
            proposal_fingerprint=self.fingerprint,
            policy_decision=approval_policy(),
            canonical_currency="USD",
        )


class NoExecution:
    async def execute_ready(self, _action_id: UUID) -> Any:
        raise AssertionError("supervisor decisions must not execute Commerce")


async def create_approval_action(
    engine: AsyncEngine,
    context: Stage6ActionContext,
    fingerprint: str,
) -> tuple[UUID, ActionTransitionService]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repository = ActionRepository(factory)
    transitions = ActionTransitionService(factory)
    action, _created = await repository.create_or_get(
        trusted_context=context.trusted_context,
        conversation_id=context.conversation_id,
        agent_run_id=context.agent_run_id,
        tool_invocation_id=context.tool_invocation_ids[0],
        proposal=CancelOrderProposal(order_id=uuid4()),
        proposal_fingerprint=fingerprint,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    await transitions.transition(
        action.id,
        action.tenant_id,
        fingerprint,
        ActionState.AWAITING_APPROVAL,
        None,
        ActionEventType.POLICY_ALLOWED,
        "allowed",
        policy_decision=approval_policy(),
    )
    return action.id, transitions


def supervisor_context(context: Stage6ActionContext) -> TrustedContext:
    return context.trusted_context.model_copy(
        update={
            "principal_id": uuid4(),
            "customer_id": None,
            "roles": frozenset({Role.SUPPORT_SUPERVISOR}),
        }
    )


def decision_service(
    transitions: ActionTransitionService,
    freshness: FixedApprovalFreshness,
) -> ActionDecisionService:
    return ActionDecisionService(
        transition_service=transitions,
        freshness_service=freshness,  # type: ignore[arg-type]
        action_executor=NoExecution(),  # type: ignore[arg-type]
        commerce_client=freshness,  # type: ignore[arg-type]
    )


async def event_types(engine: AsyncEngine, action_id: UUID) -> list[str]:
    async with engine.connect() as connection:
        return list(
            (
                await connection.execute(
                    select(ActionEvent.event_type)
                    .where(ActionEvent.action_request_id == action_id)
                    .order_by(ActionEvent.sequence)
                )
            )
            .scalars()
            .all()
        )


@pytest.mark.asyncio
async def test_concurrent_supervisor_approve_and_reject_have_one_durable_winner(
    postgres_engine: AsyncEngine,
    clean_stage6_action_tables: None,
) -> None:
    del clean_stage6_action_tables
    context = await seed_stage6_action_context(postgres_engine)
    fingerprint = "a" * 64
    action_id, transitions = await create_approval_action(postgres_engine, context, fingerprint)
    freshness = FixedApprovalFreshness(fingerprint)
    approve_service = decision_service(transitions, freshness)
    reject_service = decision_service(transitions, freshness)
    supervisor = supervisor_context(context)
    other_supervisor = supervisor.model_copy(update={"principal_id": uuid4()})

    results = await asyncio.gather(
        approve_service.approve(action_id, supervisor, fingerprint),
        reject_service.reject_approval(action_id, other_supervisor, fingerprint),
        return_exceptions=True,
    )

    successes = [result for result in results if not isinstance(result, BaseException)]
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ActionDecisionConflictError)
    types = await event_types(postgres_engine, action_id)
    assert (
        types.count(ActionEventType.SUPERVISOR_APPROVED.value)
        + types.count(ActionEventType.SUPERVISOR_REJECTED.value)
        == 1
    )
    async with postgres_engine.connect() as connection:
        stored = (
            await connection.execute(
                select(ActionRequest.state, ActionRequest.supervisor_approval_decision).where(
                    ActionRequest.id == action_id
                )
            )
        ).one()
    assert stored.state in {
        ActionState.AWAITING_CONFIRMATION.value,
        ActionState.REJECTED.value,
    }
    assert stored.supervisor_approval_decision in {"approved", "rejected"}


@pytest.mark.asyncio
async def test_concurrent_supervisor_approval_and_customer_withdrawal_are_serialized(
    postgres_engine: AsyncEngine,
    clean_stage6_action_tables: None,
) -> None:
    del clean_stage6_action_tables
    context = await seed_stage6_action_context(postgres_engine)
    fingerprint = "b" * 64
    action_id, transitions = await create_approval_action(postgres_engine, context, fingerprint)
    freshness = FixedApprovalFreshness(fingerprint)
    supervisor = supervisor_context(context)
    service = decision_service(transitions, freshness)

    results = await asyncio.gather(
        service.approve(action_id, supervisor, fingerprint),
        service.reject(action_id, context.trusted_context, fingerprint),
        return_exceptions=True,
    )

    failures = [result for result in results if isinstance(result, BaseException)]
    assert all(isinstance(failure, ActionDecisionConflictError) for failure in failures)
    types = await event_types(postgres_engine, action_id)
    assert types.count(ActionEventType.SUPERVISOR_APPROVED.value) <= 1
    assert types.count(ActionEventType.CUSTOMER_REJECTED.value) <= 1
    assert not any(event_type == ActionEventType.EXECUTION_STARTED.value for event_type in types)
