"""PostgreSQL proof that M6C records M6A actions against the exact M6C.1 trace row."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from tests.postgres.stage6.conftest import seed_stage6_action_context

from verbaops.actions.models import ActionState, CancelOrderProposal
from verbaops.actions.persistence import ActionRequest
from verbaops.actions.proposals import ActionProposalService
from verbaops.actions.repository import ActionOriginConflictError, ActionRepository
from verbaops.actions.transitions import ActionTransitionService
from verbaops.commerce.models import OrderResponse, OrderStatus, ShipmentResponse, ShipmentStatus
from verbaops.conversations.persistence import ToolInvocation

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.contract]


class FixedCommerce:
    def __init__(self, tenant_id: UUID, customer_id: UUID, order_id: UUID) -> None:
        self.tenant_id = tenant_id
        self.order = OrderResponse(
            id=order_id,
            customer_id=customer_id,
            status=OrderStatus.CONFIRMED,
            total="100.00",
            created_at=datetime(2026, 10, 1, tzinfo=UTC),
            updated_at=datetime(2026, 10, 3, tzinfo=UTC),
            items=[],
        )
        self.shipment = ShipmentResponse(
            id=uuid4(),
            order_id=order_id,
            carrier="Carrier",
            tracking_number=None,
            status=ShipmentStatus.PENDING,
            estimated_delivery=None,
            delivered_at=None,
            delivery_slot_id=None,
        )

    async def get_order(self, _order_id: UUID, _customer_id: UUID) -> OrderResponse:
        return self.order

    async def get_shipment(self, _order_id: UUID, _customer_id: UUID) -> ShipmentResponse:
        return self.shipment


@pytest.mark.asyncio
async def test_proposal_origin_is_the_durable_invocation_and_changed_replay_fails_closed(
    postgres_engine: AsyncEngine,
) -> None:
    context = await seed_stage6_action_context(postgres_engine, tool_invocation_count=1)
    invocation_id = context.tool_invocation_ids[0]
    order_id = uuid4()
    customer_id = context.trusted_context.customer_id
    assert customer_id is not None
    commerce = FixedCommerce(context.trusted_context.tenant_id, customer_id, order_id)
    factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    proposal_service = ActionProposalService(
        commerce,  # type: ignore[arg-type]
        ActionRepository(factory),
        ActionTransitionService(factory),
        now=lambda: datetime.now(UTC),
    )
    proposal = CancelOrderProposal(order_id=order_id)

    first = await proposal_service.propose(
        trusted_context=context.trusted_context,
        conversation_id=context.conversation_id,
        agent_run_id=context.agent_run_id,
        tool_invocation_id=invocation_id,
        proposal=proposal,
    )
    replay = await proposal_service.propose(
        trusted_context=context.trusted_context,
        conversation_id=context.conversation_id,
        agent_run_id=context.agent_run_id,
        tool_invocation_id=invocation_id,
        proposal=proposal,
    )

    assert first.action_request_id == replay.action_request_id
    assert first.state is replay.state is ActionState.AWAITING_CONFIRMATION
    async with factory() as session:
        action = await session.get(ActionRequest, first.action_request_id)
        invocation = await session.get(ToolInvocation, invocation_id)
        assert action is not None and invocation is not None
        assert action.originating_tool_invocation_id == invocation.id
        assert action.agent_run_id == invocation.agent_run_id == context.agent_run_id
        linked_actions = await session.scalars(
            select(ActionRequest).where(
                ActionRequest.originating_tool_invocation_id == invocation.id
            )
        )
        assert len(list(linked_actions)) == 1

    commerce.order = commerce.order.model_copy(
        update={"status": OrderStatus.PROCESSING, "updated_at": datetime.now(UTC)}
    )
    with pytest.raises(ActionOriginConflictError):
        await proposal_service.propose(
            trusted_context=context.trusted_context,
            conversation_id=context.conversation_id,
            agent_run_id=context.agent_run_id,
            tool_invocation_id=invocation_id,
            proposal=proposal,
        )
