"""Contracts for typed, non-executing Stage 6 proposal tools."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from verbaops.actions.models import (
    ActionRequestSummary,
    ActionState,
    CancelOrderProposal,
    RefundProposal,
    RescheduleDeliveryProposal,
    ReturnItemProposal,
    ReturnProposal,
    SupportTicketProposal,
    TicketCategory,
)
from verbaops.auth.context import Role, TrustedContext
from verbaops.commerce.client import CommerceClient
from verbaops.config import CommerceSettings
from verbaops.tools.stage6_commerce_reads import (
    list_delivery_slots as stage6_list_delivery_slots,
)
from verbaops.tools.stage6_commerce_reads import (
    search_products as stage6_search_products,
)
from verbaops.tools.stage6_models import Stage6ToolExecutionContext
from verbaops.tools.stage6_registry import build_stage6_tool_registry

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
CUSTOMER_ID = UUID("20000000-0000-4000-8000-000000000002")
ORDER_ID = UUID("30000000-0000-4000-8000-000000000003")
SLOT_ID = UUID("40000000-0000-4000-8000-000000000004")
ITEM_ID = UUID("50000000-0000-4000-8000-000000000005")


def _context() -> Stage6ToolExecutionContext:
    return Stage6ToolExecutionContext(
        trusted_context=TrustedContext(
            principal_id=UUID("60000000-0000-4000-8000-000000000006"),
            tenant_id=TENANT_ID,
            customer_id=CUSTOMER_ID,
            roles=frozenset({Role.CUSTOMER}),
        ),
        conversation_id=UUID("70000000-0000-4000-8000-000000000007"),
        agent_run_id=UUID("80000000-0000-4000-8000-000000000008"),
        tool_invocation_id=UUID("90000000-0000-4000-8000-000000000009"),
    )


def _proposals() -> tuple[tuple[str, Any], ...]:
    return (
        (
            "propose_reschedule_delivery",
            RescheduleDeliveryProposal(order_id=ORDER_ID, delivery_slot_id=SLOT_ID),
        ),
        ("propose_cancel_order", CancelOrderProposal(order_id=ORDER_ID)),
        (
            "propose_return",
            ReturnProposal(
                order_id=ORDER_ID,
                items=(ReturnItemProposal(order_item_id=ITEM_ID, quantity=1),),
                reason="Wrong size",
            ),
        ),
        (
            "propose_support_ticket",
            SupportTicketProposal(
                order_id=ORDER_ID,
                category=TicketCategory.ORDER,
                subject="Order question",
                description="Please check this order.",
            ),
        ),
        (
            "propose_refund",
            RefundProposal(order_id=ORDER_ID, amount=Decimal("15.00"), reason="Duplicate charge"),
        ),
    )


@dataclass
class ProposalServiceSpy:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def propose(self, **kwargs: Any) -> ActionRequestSummary:
        self.calls.append(kwargs)
        return ActionRequestSummary(
            action_request_id=uuid4(),
            action_type=kwargs["proposal"].action_type,
            state=ActionState.AWAITING_CONFIRMATION,
            proposal_fingerprint="a" * 64,
            safe_summary="A proposal is waiting for customer confirmation.",
            required_next_actor="customer",
            reason_code="allowed",
        )


@pytest.mark.parametrize("tool_name,proposal", _proposals())
def test_each_proposal_tool_has_only_its_typed_action_fields(tool_name: str, proposal: Any) -> None:
    service = ProposalServiceSpy()
    definition = build_stage6_tool_registry(service).get(tool_name)
    schema_fields = set(definition.input_model.model_json_schema()["properties"])
    assert schema_fields == set(type(proposal).model_fields)
    assert set(definition.output_model.model_fields) == {
        "action_request_id",
        "action_type",
        "state",
        "proposal_fingerprint",
        "safe_summary",
        "required_next_actor",
        "reason_code",
    }
    assert definition.retry_policy.max_attempts == 1
    assert definition.retry_policy.retryable_status_codes == ()
    assert not schema_fields & {
        "tenant_id",
        "customer_id",
        "principal_id",
        "roles",
        "customer_confirmation",
        "supervisor_approval",
        "approval_required",
        "confirmation_required",
        "state",
        "currency",
        "action_request_id",
        "tool_invocation_id",
        "idempotency_key",
        "url",
        "credentials",
    }
    with pytest.raises(ValidationError):
        definition.input_model.model_validate(
            {**proposal.model_dump(mode="python"), "customer_id": CUSTOMER_ID}
        )


@pytest.mark.parametrize(
    ("tool_name", "proposal"),
    [
        ("propose_return", _proposals()[2][1]),
        ("propose_refund", _proposals()[4][1]),
    ],
)
def test_commerce_reason_limits_are_enforced_at_model_tool_boundary(
    tool_name: str, proposal: Any
) -> None:
    import json

    definition = build_stage6_tool_registry(ProposalServiceSpy()).get(tool_name)
    raw_input = proposal.model_dump(mode="json")
    raw_input["reason"] = "x" * 501

    with pytest.raises(ValidationError):
        definition.input_model.model_validate_json(json.dumps(raw_input))


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,proposal", _proposals())
async def test_proposal_handler_injects_authenticated_scope_and_durable_invocation(
    tool_name: str, proposal: Any
) -> None:
    service = ProposalServiceSpy()
    registry = build_stage6_tool_registry(service)
    handler_methods: list[str] = []

    def commerce_handler(request: httpx.Request) -> httpx.Response:
        handler_methods.append(request.method)
        raise AssertionError("proposal handler must not access Commerce")

    commerce = CommerceClient(
        CommerceSettings(base_url="http://commerce.test", service_token=SecretStr("test-token")),
        httpx.AsyncClient(transport=httpx.MockTransport(commerce_handler)),
    )
    result = await registry.execute(
        tool_name,
        proposal.model_dump(mode="json"),
        _context(),
        commerce,
    )

    assert isinstance(result, ActionRequestSummary)
    assert len(service.calls) == 1
    call = service.calls[0]
    assert call["trusted_context"] == _context().trusted_context
    assert call["conversation_id"] == _context().conversation_id
    assert call["agent_run_id"] == _context().agent_run_id
    assert call["tool_invocation_id"] == _context().tool_invocation_id
    assert call["proposal"] == proposal
    assert handler_methods == []
    await commerce._http_client.aclose()


def test_stage6_registry_is_the_explicit_five_read_plus_five_proposal_allowlist() -> None:
    registry = build_stage6_tool_registry(ProposalServiceSpy())
    names = set(registry.names)
    assert names == {
        "get_order_status",
        "get_shipment_status",
        "get_refund_status",
        "search_products",
        "list_delivery_slots",
        "propose_reschedule_delivery",
        "propose_cancel_order",
        "propose_return",
        "propose_support_ticket",
        "propose_refund",
    }
    assert not any(
        marker in name
        for name in names
        for marker in ("execute", "confirm", "approve", "arbitrary_http")
    )
    search_handler = cast(object, registry.get("search_products").handler)
    slots_handler = cast(object, registry.get("list_delivery_slots").handler)
    assert search_handler is stage6_search_products
    assert slots_handler is stage6_list_delivery_slots
