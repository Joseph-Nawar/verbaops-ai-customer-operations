"""Explicit proposal handlers that persist workflow requests without executing them."""

from typing import Any

from verbaops.actions.models import (
    ActionRequestSummary,
    CancelOrderProposal,
    RefundProposal,
    RescheduleDeliveryProposal,
    ReturnProposal,
    SupportTicketProposal,
)
from verbaops.actions.proposals import ActionProposalService
from verbaops.tools.stage6_models import (
    CancelOrderToolInput,
    RefundToolInput,
    RescheduleDeliveryToolInput,
    ReturnToolInput,
    Stage6ToolExecutionContext,
    SupportTicketToolInput,
)


def build_proposal_handlers(
    service: ActionProposalService,
) -> tuple[tuple[str, type[Any], str, Any], ...]:
    """Return the five explicit name/input/description/handler bindings."""

    async def propose_reschedule_delivery(
        proposal_input: RescheduleDeliveryToolInput,
        context: Any,
        _commerce: Any,
    ) -> ActionRequestSummary:
        proposal = RescheduleDeliveryProposal.model_validate_json(proposal_input.model_dump_json())
        return await service.propose(**_service_arguments(proposal, context))

    async def propose_cancel_order(
        proposal_input: CancelOrderToolInput,
        context: Any,
        _commerce: Any,
    ) -> ActionRequestSummary:
        proposal = CancelOrderProposal.model_validate_json(proposal_input.model_dump_json())
        return await service.propose(**_service_arguments(proposal, context))

    async def propose_return(
        proposal_input: ReturnToolInput,
        context: Any,
        _commerce: Any,
    ) -> ActionRequestSummary:
        proposal = ReturnProposal.model_validate_json(proposal_input.model_dump_json())
        return await service.propose(**_service_arguments(proposal, context))

    async def propose_support_ticket(
        proposal_input: SupportTicketToolInput,
        context: Any,
        _commerce: Any,
    ) -> ActionRequestSummary:
        proposal = SupportTicketProposal.model_validate_json(proposal_input.model_dump_json())
        return await service.propose(**_service_arguments(proposal, context))

    async def propose_refund(
        proposal_input: RefundToolInput,
        context: Any,
        _commerce: Any,
    ) -> ActionRequestSummary:
        proposal = RefundProposal.model_validate_json(proposal_input.model_dump_json())
        return await service.propose(**_service_arguments(proposal, context))

    return (
        (
            "propose_reschedule_delivery",
            RescheduleDeliveryToolInput,
            "Create a typed delivery reschedule proposal. This does not change the delivery.",
            propose_reschedule_delivery,
        ),
        (
            "propose_cancel_order",
            CancelOrderToolInput,
            "Create a typed order cancellation proposal. This does not cancel the order.",
            propose_cancel_order,
        ),
        (
            "propose_return",
            ReturnToolInput,
            "Create a typed return proposal. This does not create a Commerce return.",
            propose_return,
        ),
        (
            "propose_support_ticket",
            SupportTicketToolInput,
            "Create a typed support ticket proposal. This does not create a Commerce ticket.",
            propose_support_ticket,
        ),
        (
            "propose_refund",
            RefundToolInput,
            "Create a typed refund proposal. This does not issue a refund.",
            propose_refund,
        ),
    )


def _service_arguments(proposal: Any, context: Stage6ToolExecutionContext) -> dict[str, Any]:
    return {
        "trusted_context": context.trusted_context,
        "conversation_id": context.conversation_id,
        "agent_run_id": context.agent_run_id,
        "tool_invocation_id": context.tool_invocation_id,
        "proposal": proposal,
    }
