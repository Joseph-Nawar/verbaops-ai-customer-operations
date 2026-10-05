"""Customer-only action decisions bind fresh confirmation to durable lifecycle state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from verbaops.actions.decisions import (
    ActionDecisionConflictError,
    ActionDecisionForbiddenError,
    ActionDecisionService,
    ActionFreshnessUnavailableError,
)
from verbaops.actions.executor import ActionExecutor
from verbaops.actions.models import (
    ActionProposal,
    ActionState,
    ActionType,
    CancelOrderProposal,
    RefundProposal,
    RescheduleDeliveryProposal,
    ReturnItemProposal,
    ReturnProposal,
    SupportTicketProposal,
    TicketCategory,
    proposal_target_ids,
)
from verbaops.actions.policy import PolicyDecision
from verbaops.actions.proposals import ActionProposalService
from verbaops.actions.transitions import (
    ActionEventType,
    ActionExpiredError,
    ActionRequestRecord,
    ActionTransitionService,
)
from verbaops.auth.context import Role, TrustedContext
from verbaops.commerce.client import CommerceClient
from verbaops.commerce.errors import CommerceUnavailableError

NOW = datetime.now(UTC)


def context(
    *, roles: frozenset[Role] | None = None, customer_id: UUID | None = None
) -> TrustedContext:
    return TrustedContext(
        principal_id=uuid4(),
        tenant_id=uuid4(),
        customer_id=customer_id or uuid4(),
        roles=roles or frozenset({Role.CUSTOMER}),
    )


def action_record(
    trusted: TrustedContext,
    *,
    state: ActionState = ActionState.AWAITING_CONFIRMATION,
    proposal: ActionProposal | None = None,
    fingerprint: str = "a" * 64,
    approval_required: bool = False,
) -> SimpleNamespace:
    proposal = proposal or CancelOrderProposal(order_id=uuid4())
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=trusted.tenant_id,
        customer_id=trusted.customer_id,
        proposing_principal_id=trusted.principal_id,
        action_type=proposal.action_type,
        proposal_payload=proposal.model_dump(mode="json"),
        target_ids=proposal_target_ids(proposal),
        proposal_schema_version="action-proposal-v1",
        proposal_fingerprint=fingerprint,
        state=state,
        policy_allowed=True,
        policy_reason_code="allowed",
        policy_version="stage6-policy-v1",
        policy_observed_at=NOW,
        confirmation_required=True,
        approval_required=approval_required,
        customer_confirmation_decision=(
            "confirmed" if state in {ActionState.READY_TO_EXECUTE, ActionState.SUCCEEDED} else None
        ),
        customer_confirmation_actor_id=None,
        customer_confirmation_at=None,
        customer_confirmation_fingerprint=(
            fingerprint if state in {ActionState.READY_TO_EXECUTE, ActionState.SUCCEEDED} else None
        ),
        supervisor_approval_decision=None,
        supervisor_approval_fingerprint=None,
        idempotency_key=uuid4(),
        expires_at=NOW + timedelta(hours=1),
        execution_attempt_count=0,
        execution_lease_owner=None,
        execution_lease_expires_at=None,
        commerce_resource_id=None,
        commerce_status_code=None,
        commerce_error_code=None,
        verification_status=None,
        verified_resource_id=None,
        verified_at=None,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeTransitions:
    def __init__(self, record: SimpleNamespace) -> None:
        self.record = record
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def get_scoped(self, action_id: UUID, tenant_id: UUID, customer_id: UUID) -> Any:
        if (
            action_id != self.record.id
            or tenant_id != self.record.tenant_id
            or customer_id != self.record.customer_id
        ):
            from verbaops.actions.transitions import ActionRequestNotFoundError

            raise ActionRequestNotFoundError("action request not found in customer scope")
        return self.record

    async def transition(self, *args: Any, **kwargs: Any) -> Any:
        target_state = args[3]
        actor_id = args[4]
        event_type = args[5]
        reason_code = args[6]
        if target_state is not ActionState.EXPIRED and self.record.expires_at <= datetime.now(UTC):
            self.record.state = ActionState.EXPIRED
            self.record.version += 1
            raise ActionExpiredError(cast(ActionRequestRecord, self.record))
        self.calls.append(
            (
                "transition",
                kwargs
                | {
                    "target_state": target_state,
                    "event_type": event_type,
                    "reason_code": reason_code,
                },
            )
        )
        if target_state is ActionState.EXPIRED:
            self.record.state = ActionState.EXPIRED
        else:
            self.record.state = target_state
            if event_type is ActionEventType.CUSTOMER_CONFIRMED:
                self.record.customer_confirmation_decision = "confirmed"
            elif event_type is ActionEventType.CUSTOMER_REJECTED:
                self.record.customer_confirmation_decision = "rejected"
            self.record.customer_confirmation_actor_id = actor_id
            self.record.customer_confirmation_at = datetime.now(UTC)
            self.record.customer_confirmation_fingerprint = self.record.proposal_fingerprint
        self.record.version += 1
        return self.record


class FakeFreshness:
    def __init__(
        self,
        *,
        fingerprint: str = "a" * 64,
        allowed: bool = True,
        approval: bool = False,
        currency: str | None = "USD",
        error: Exception | None = None,
        tenant_id: UUID | None = None,
    ):
        self.fingerprint = fingerprint
        self.allowed = allowed
        self.approval = approval
        self.currency = currency
        self.error = error
        self.tenant_id = tenant_id
        self.calls = 0
        self.currency_calls = 0

    async def refresh(self, _record: object) -> SimpleNamespace:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            proposal_fingerprint=self.fingerprint,
            policy_decision=PolicyDecision(
                allowed=self.allowed,
                reason_code="allowed" if self.allowed else "commerce_ineligible",
                confirmation_required=self.allowed,
                approval_required=self.approval,
                policy_version="stage6-policy-v1",
            ),
            canonical_currency=self.currency,
        )

    async def get_tenant_currency(self) -> SimpleNamespace | None:
        self.currency_calls += 1
        if self.error is not None:
            raise self.error
        if self.currency is None:
            return None
        return SimpleNamespace(currency_code=self.currency)


class FakeExecutor:
    def __init__(self, transitions: FakeTransitions) -> None:
        self.transitions = transitions
        self.calls: list[object] = []

    async def execute_ready(self, action_id: UUID) -> SimpleNamespace:
        self.calls.append(action_id)
        return self.transitions.record


def service_for(
    trusted: TrustedContext,
    *,
    record: SimpleNamespace | None = None,
    freshness: FakeFreshness | None = None,
    commerce_tenant_id: UUID | None = None,
) -> tuple[ActionDecisionService, FakeTransitions, FakeFreshness, FakeExecutor]:
    action = record or action_record(trusted)
    transitions = FakeTransitions(action)
    current_freshness = freshness or FakeFreshness()
    current_freshness.tenant_id = commerce_tenant_id or action.tenant_id
    executor = FakeExecutor(transitions)
    service = ActionDecisionService(
        transition_service=cast(ActionTransitionService, transitions),
        freshness_service=cast(ActionProposalService, current_freshness),
        action_executor=cast(ActionExecutor, executor),
        commerce_client=cast(CommerceClient, current_freshness),
    )
    return service, transitions, current_freshness, executor


@pytest.mark.asyncio
async def test_confirmation_refreshes_then_commits_before_internal_execution() -> None:
    trusted = context()
    service, transitions, freshness, executor = service_for(trusted)

    result = await service.confirm(
        transitions.record.id, trusted, transitions.record.proposal_fingerprint
    )

    assert freshness.calls == 1
    assert transitions.record.state is ActionState.READY_TO_EXECUTE
    assert transitions.record.customer_confirmation_decision == "confirmed"
    assert transitions.record.customer_confirmation_actor_id == trusted.principal_id
    assert transitions.calls[0][1]["event_type"] is ActionEventType.CUSTOMER_CONFIRMED
    assert executor.calls == [transitions.record.id]
    assert result.state is ActionState.READY_TO_EXECUTE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("freshness", "reason"),
    [
        (FakeFreshness(fingerprint="b" * 64), "stale"),
        (FakeFreshness(allowed=False), "stale"),
        (FakeFreshness(approval=True), "stale"),
    ],
)
async def test_changed_facts_or_policy_expire_before_customer_confirmation(
    freshness: FakeFreshness, reason: str
) -> None:
    trusted = context()
    service, transitions, _, executor = service_for(trusted, freshness=freshness)

    with pytest.raises(ActionDecisionConflictError):
        await service.confirm(
            transitions.record.id, trusted, transitions.record.proposal_fingerprint
        )

    assert transitions.record.state is ActionState.EXPIRED
    assert transitions.calls[0][1]["reason_code"] == reason
    assert executor.calls == []


@pytest.mark.asyncio
async def test_customer_confirmation_cannot_skip_a_required_supervisor_gate() -> None:
    trusted = context()
    record = action_record(trusted, state=ActionState.AWAITING_CONFIRMATION, approval_required=True)
    service, transitions, freshness, executor = service_for(
        trusted, record=record, freshness=FakeFreshness(approval=True)
    )

    with pytest.raises(ActionDecisionConflictError):
        await service.confirm(record.id, trusted, record.proposal_fingerprint)

    assert transitions.record.state is ActionState.EXPIRED
    assert executor.calls == []
    assert freshness.calls == 1


@pytest.mark.asyncio
async def test_wrong_fingerprint_and_early_high_risk_confirmation_conflict() -> None:
    trusted = context()
    service, transitions, freshness, executor = service_for(trusted)
    with pytest.raises(ActionDecisionConflictError):
        await service.confirm(transitions.record.id, trusted, "f" * 64)
    assert freshness.calls == 0
    assert executor.calls == []

    waiting_for_supervisor = action_record(
        trusted, state=ActionState.AWAITING_APPROVAL, approval_required=True
    )
    service, transitions, freshness, executor = service_for(trusted, record=waiting_for_supervisor)
    with pytest.raises(ActionDecisionConflictError):
        await service.confirm(
            transitions.record.id, trusted, transitions.record.proposal_fingerprint
        )
    assert freshness.calls == 0
    assert executor.calls == []


@pytest.mark.asyncio
async def test_expired_proposal_cannot_be_confirmed() -> None:
    trusted = context()
    record = action_record(trusted)
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    service, transitions, freshness, executor = service_for(trusted, record=record)

    with pytest.raises(ActionDecisionConflictError):
        await service.confirm(record.id, trusted, record.proposal_fingerprint)

    assert transitions.record.state is ActionState.EXPIRED
    assert freshness.calls == 1
    assert executor.calls == []


@pytest.mark.asyncio
async def test_same_confirmation_retry_is_idempotent_and_opposite_decision_conflicts() -> None:
    trusted = context()
    record = action_record(trusted, state=ActionState.READY_TO_EXECUTE)
    service, _transitions, freshness, executor = service_for(trusted, record=record)

    result = await service.confirm(record.id, trusted, record.proposal_fingerprint)

    assert result.state is ActionState.READY_TO_EXECUTE
    assert freshness.calls == 0
    assert executor.calls == [record.id]
    with pytest.raises(ActionDecisionConflictError):
        await service.reject(record.id, trusted, record.proposal_fingerprint)


@pytest.mark.asyncio
async def test_customer_can_reject_confirmation_or_withdraw_approval_without_execution() -> None:
    for state, approval_required in (
        (ActionState.AWAITING_CONFIRMATION, False),
        (ActionState.AWAITING_APPROVAL, True),
    ):
        trusted = context()
        record = action_record(trusted, state=state, approval_required=approval_required)
        service, transitions, freshness, executor = service_for(trusted, record=record)

        result = await service.reject(record.id, trusted, record.proposal_fingerprint)

        assert result.state is ActionState.REJECTED
        assert result.customer_decision == "rejected"
        assert transitions.record.customer_confirmation_actor_id == trusted.principal_id
        assert transitions.calls[-1][1]["event_type"] is ActionEventType.CUSTOMER_REJECTED
        assert freshness.calls == 0
        assert executor.calls == []


@pytest.mark.asyncio
async def test_repeated_customer_rejection_is_idempotent_but_confirmation_cannot_overwrite() -> (
    None
):
    trusted = context()
    record = action_record(trusted, state=ActionState.REJECTED)
    record.customer_confirmation_decision = "rejected"
    record.customer_confirmation_fingerprint = record.proposal_fingerprint
    record.customer_confirmation_actor_id = trusted.principal_id
    service, transitions, _, executor = service_for(trusted, record=record)

    result = await service.reject(record.id, trusted, record.proposal_fingerprint)

    assert result.state is ActionState.REJECTED
    assert transitions.calls == []
    assert executor.calls == []
    with pytest.raises(ActionDecisionConflictError):
        await service.confirm(record.id, trusted, record.proposal_fingerprint)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "roles",
    [
        frozenset({Role.CUSTOMER}),
        frozenset({Role.CUSTOMER, Role.TENANT_ADMIN}),
        frozenset({Role.CUSTOMER, Role.SUPPORT_AGENT}),
        frozenset({Role.CUSTOMER, Role.SUPPORT_SUPERVISOR}),
    ],
)
async def test_composed_customer_roles_can_view_confirm_and_reject(
    roles: frozenset[Role],
) -> None:
    trusted = context(roles=roles)
    service, transitions, freshness, executor = service_for(trusted)

    view = await service.get_action_request(transitions.record.id, trusted)
    confirmed = await service.confirm(
        transitions.record.id, trusted, transitions.record.proposal_fingerprint
    )

    assert view.state is ActionState.AWAITING_CONFIRMATION
    assert confirmed.state is ActionState.READY_TO_EXECUTE
    assert freshness.calls == 1
    assert executor.calls == [transitions.record.id]

    reject_service, reject_transitions, _, reject_executor = service_for(
        trusted, record=action_record(trusted)
    )
    rejected = await reject_service.reject(
        reject_transitions.record.id,
        trusted,
        reject_transitions.record.proposal_fingerprint,
    )

    assert rejected.state is ActionState.REJECTED
    assert reject_executor.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "roles",
    [
        frozenset({Role.SUPPORT_AGENT}),
        frozenset({Role.SUPPORT_SUPERVISOR}),
        frozenset({Role.TENANT_ADMIN}),
        frozenset({Role.SUPPORT_AGENT, Role.SUPPORT_SUPERVISOR}),
    ],
)
async def test_non_customer_roles_cannot_decide_for_a_bound_customer(
    roles: frozenset[Role],
) -> None:
    trusted = context(roles=roles)
    service, transitions, freshness, executor = service_for(trusted)

    with pytest.raises(ActionDecisionForbiddenError):
        await service.get_action_request(transitions.record.id, trusted)
    with pytest.raises(ActionDecisionForbiddenError):
        await service.confirm(
            transitions.record.id, trusted, transitions.record.proposal_fingerprint
        )
    with pytest.raises(ActionDecisionForbiddenError):
        await service.reject(
            transitions.record.id, trusted, transitions.record.proposal_fingerprint
        )

    assert freshness.calls == 0
    assert freshness.currency_calls == 0
    assert transitions.calls == []
    assert executor.calls == []


@pytest.mark.asyncio
async def test_customer_role_without_customer_binding_fails_closed() -> None:
    trusted = TrustedContext(
        principal_id=uuid4(),
        tenant_id=uuid4(),
        customer_id=None,
        roles=frozenset({Role.CUSTOMER}),
    )
    service, transitions, freshness, executor = service_for(trusted)

    with pytest.raises(ActionDecisionForbiddenError):
        await service.get_action_request(transitions.record.id, trusted)

    assert freshness.calls == 0
    assert freshness.currency_calls == 0
    assert transitions.calls == []
    assert executor.calls == []


@pytest.mark.asyncio
async def test_customer_view_contains_only_safe_action_projection() -> None:
    trusted = context()
    record = action_record(
        trusted,
        proposal=RefundProposal(order_id=uuid4(), amount=Decimal("45.00"), reason="damaged"),
    )
    record.idempotency_key = uuid4()
    record.execution_lease_owner = uuid4()
    record.commerce_error_code = "private_internal_code"
    service, _, _, _ = service_for(trusted, record=record)

    view = await service.get_action_request(record.id, trusted)

    assert view.action_request_id == record.id
    assert view.action_type is ActionType.REQUEST_REFUND
    assert isinstance(view.proposal, RefundProposal)
    assert view.proposal.amount == Decimal("45.00")
    assert view.required_next_actor == "customer"
    assert view.safe_summary == (
        f"Request a refund of 45.00 USD for order {record.target_ids[0]}; "
        "this creates a request, not a payment."
    )
    assert "tenant_id" not in view.model_dump()
    assert "idempotency_key" not in view.model_dump()
    assert "execution_lease_owner" not in view.model_dump()
    assert "commerce_error_code" not in view.model_dump()


@pytest.mark.asyncio
async def test_non_refund_get_is_only_a_durable_scoped_projection() -> None:
    trusted = context()
    record = action_record(trusted)
    freshness = FakeFreshness(error=CommerceUnavailableError())
    service, transitions, _, executor = service_for(trusted, record=record, freshness=freshness)

    view = await service.get_action_request(record.id, trusted)

    assert view.state is ActionState.AWAITING_CONFIRMATION
    assert freshness.calls == 0
    assert freshness.currency_calls == 0
    assert transitions.calls == []
    assert executor.calls == []


@pytest.mark.asyncio
async def test_refund_get_skips_currency_enrichment_for_a_wrong_tenant_client() -> None:
    trusted = context()
    record = action_record(
        trusted,
        proposal=RefundProposal(order_id=uuid4(), amount=Decimal("45.00"), reason="damaged"),
    )
    freshness = FakeFreshness(currency="EUR")
    service, transitions, _, executor = service_for(
        trusted,
        record=record,
        freshness=freshness,
        commerce_tenant_id=uuid4(),
    )

    view = await service.get_action_request(record.id, trusted)

    assert view.currency_code is None
    assert freshness.currency_calls == 0
    assert transitions.calls == []
    assert executor.calls == []


@pytest.mark.asyncio
async def test_pending_refund_view_includes_trusted_currency_and_request_only_meaning() -> None:
    trusted = context()
    record = action_record(
        trusted,
        proposal=RefundProposal(order_id=uuid4(), amount=Decimal("45.00"), reason="damaged"),
    )
    service, _, freshness, _ = service_for(trusted, record=record)

    view = await service.get_action_request(record.id, trusted)

    assert freshness.calls == 0
    assert freshness.currency_calls == 1
    assert view.currency_code == "USD"
    assert "45.00 USD" in view.safe_summary
    assert "request, not a payment" in view.safe_summary


@pytest.mark.asyncio
async def test_stale_refund_view_does_not_expire_but_confirmation_does() -> None:
    trusted = context()
    record = action_record(
        trusted,
        proposal=RefundProposal(order_id=uuid4(), amount=Decimal("45.00"), reason="damaged"),
    )
    freshness = FakeFreshness(fingerprint="b" * 64, currency="EUR")
    service, transitions, _, _ = service_for(trusted, record=record, freshness=freshness)

    view = await service.get_action_request(record.id, trusted)

    assert view.state is ActionState.AWAITING_CONFIRMATION
    assert view.currency_code == "EUR"
    assert freshness.calls == 0
    assert transitions.calls == []

    with pytest.raises(ActionDecisionConflictError):
        await service.confirm(record.id, trusted, record.proposal_fingerprint)

    assert transitions.record.state is ActionState.EXPIRED
    assert transitions.calls[-1][1]["reason_code"] == "stale"


@pytest.mark.asyncio
async def test_pending_refund_view_fails_closed_without_currency() -> None:
    trusted = context()
    record = action_record(
        trusted,
        proposal=RefundProposal(order_id=uuid4(), amount=Decimal("45.00"), reason="damaged"),
    )
    service, transitions, freshness, executor = service_for(
        trusted, record=record, freshness=FakeFreshness(currency=None)
    )

    view = await service.get_action_request(record.id, trusted)

    assert view.state is ActionState.AWAITING_CONFIRMATION
    assert view.currency_code is None
    assert "45.00" not in view.safe_summary
    assert freshness.calls == 0
    assert freshness.currency_calls == 1
    assert transitions.calls == []
    assert executor.calls == []


@pytest.mark.asyncio
async def test_refund_view_returns_durable_state_during_commerce_outage() -> None:
    trusted = context()
    record = action_record(
        trusted,
        proposal=RefundProposal(order_id=uuid4(), amount=Decimal("45.00"), reason="damaged"),
    )
    service, transitions, freshness, executor = service_for(
        trusted, record=record, freshness=FakeFreshness(error=CommerceUnavailableError())
    )

    view = await service.get_action_request(record.id, trusted)

    assert view.state is ActionState.AWAITING_CONFIRMATION
    assert view.currency_code is None
    assert freshness.calls == 0
    assert freshness.currency_calls == 1
    assert transitions.calls == []
    assert executor.calls == []

    with pytest.raises(ActionFreshnessUnavailableError):
        await service.confirm(record.id, trusted, record.proposal_fingerprint)

    assert transitions.record.state is ActionState.AWAITING_CONFIRMATION
    assert freshness.calls == 1
    assert transitions.calls == []


@pytest.mark.asyncio
async def test_customer_view_summarizes_each_non_refund_proposal_type() -> None:
    trusted = context()
    order_id = uuid4()
    proposals: tuple[ActionProposal, ...] = (
        RescheduleDeliveryProposal(order_id=order_id, delivery_slot_id=uuid4()),
        ReturnProposal(
            order_id=order_id,
            reason="damaged",
            items=(ReturnItemProposal(order_item_id=uuid4(), quantity=1),),
        ),
        SupportTicketProposal(
            order_id=None,
            category=TicketCategory.OTHER,
            subject="Need help",
            description="Please help",
        ),
    )

    for proposal in proposals:
        record = action_record(
            trusted,
            state=ActionState.AWAITING_APPROVAL,
            proposal=proposal,
            approval_required=True,
        )
        service, _, _, _ = service_for(trusted, record=record)

        view = await service.get_action_request(record.id, trusted)

        assert view.required_next_actor == "support_supervisor"
        assert proposal.action_type is view.action_type
        assert view.safe_summary
