"""M6F.1 RED tests for durable action views in conversation responses."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI

from tests.api.conftest import build_context, build_provider, build_settings, request
from tests.api.test_conversations_m3e import FakeAgentRuntime, _message, _result
from verbaops.actions.models import ActionState, ActionType
from verbaops.api.app import create_app
from verbaops.api.dependencies import get_agent_runtime, get_conversation_service
from verbaops.auth.context import Role, TrustedContext
from verbaops.conversations.domain import ConversationRecord, ConversationScope, MessagePage
from verbaops.conversations.errors import ConversationNotFoundError

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
CONVERSATION_ID = UUID("80000000-0000-0000-0000-000000000031")


def customer_context() -> TrustedContext:
    base = build_context()
    return TrustedContext(
        principal_id=base.principal_id,
        tenant_id=base.tenant_id,
        customer_id=base.customer_id,
        roles=frozenset({Role.CUSTOMER}),
    )


def active_record(context: TrustedContext) -> SimpleNamespace:
    order_id = uuid4()
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=context.tenant_id,
        customer_id=context.customer_id,
        proposing_principal_id=context.principal_id,
        conversation_id=CONVERSATION_ID,
        action_type=ActionType.CANCEL_ORDER,
        proposal_payload={"action_type": "cancel_order", "order_id": str(order_id)},
        target_ids=(order_id,),
        proposal_schema_version="action-proposal-v1",
        proposal_fingerprint="b" * 64,
        state=ActionState.AWAITING_CONFIRMATION,
        policy_allowed=True,
        policy_reason_code="allowed",
        policy_version="stage6-policy-v1",
        policy_observed_at=NOW,
        confirmation_required=True,
        approval_required=False,
        customer_confirmation_decision=None,
        customer_confirmation_actor_id=None,
        customer_confirmation_at=None,
        customer_confirmation_fingerprint=None,
        supervisor_approval_decision=None,
        supervisor_approval_actor_id=None,
        supervisor_approval_at=None,
        supervisor_approval_fingerprint=None,
        idempotency_key=uuid4(),
        expires_at=NOW,
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


class ActionConversationService:
    def __init__(self, context: TrustedContext, records: list[object]) -> None:
        self.context = context
        self.conversation = ConversationRecord(
            id=CONVERSATION_ID,
            tenant_id=context.tenant_id,
            principal_id=context.principal_id,
            customer_id=context.customer_id,
            created_at=NOW,
            updated_at=NOW,
        )
        self.records = records

    async def get_conversation(
        self, scope: ConversationScope, conversation_id: UUID
    ) -> ConversationRecord:
        if (
            conversation_id != self.conversation.id
            or scope.principal_id != self.conversation.principal_id
        ):
            raise ConversationNotFoundError()
        return self.conversation

    async def list_messages_page(
        self,
        scope: ConversationScope,
        conversation_id: UUID,
        *,
        limit: int,
        before_sequence: int | None,
    ) -> MessagePage:
        if conversation_id != self.conversation.id:
            raise ConversationNotFoundError()
        messages = (_message("user", 1, "hello"), _message("assistant", 2, "pending"))
        return MessagePage(messages=messages, has_more=False, next_before_sequence=None)

    async def list_active_action_requests(
        self, scope: ConversationScope, conversation_id: UUID, customer_id: UUID | None
    ) -> list[object]:
        assert scope.tenant_id == self.conversation.tenant_id
        assert customer_id == self.conversation.customer_id
        assert conversation_id == self.conversation.id
        return list(self.records)


@pytest.mark.asyncio
async def test_message_response_exposes_server_owned_action_summary(app: FastAPI) -> None:
    context = customer_context()
    service = ActionConversationService(context, [])
    result = _result()
    action_id = uuid4()
    from dataclasses import replace

    from verbaops.actions.models import ActionRequestSummary

    structured_action = ActionRequestSummary(
        action_request_id=action_id,
        action_type=ActionType.CANCEL_ORDER,
        state=ActionState.AWAITING_CONFIRMATION,
        proposal_fingerprint="a" * 64,
        safe_summary="Cancel order request is awaiting customer confirmation.",
        required_next_actor="customer",
        reason_code="allowed",
    )
    result = replace(result, action_requests=(structured_action,))
    app.dependency_overrides[get_conversation_service] = lambda: service
    app.dependency_overrides[get_agent_runtime] = lambda: FakeAgentRuntime(result)
    try:
        response = await request(
            app,
            "POST",
            f"/v1/conversations/{CONVERSATION_ID}/messages",
            headers={"Authorization": "Bearer opaque-test-credential"},
            json={"content": "cancel my order"},
        )
        assert response.status_code == 200
        assert response.json()["action_requests"] == [structured_action.model_dump(mode="json")]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_conversation_reload_uses_durable_active_action_rows_not_tool_json() -> None:
    context = customer_context()
    service = ActionConversationService(context, [active_record(context)])
    app = create_app(settings=build_settings(), auth_provider=build_provider(context))
    app.dependency_overrides[get_conversation_service] = lambda: service
    try:
        response = await request(
            app,
            "GET",
            f"/v1/conversations/{CONVERSATION_ID}",
            headers={"Authorization": "Bearer opaque-test-credential"},
        )
        assert response.status_code == 200
        action = response.json()["active_action_requests"][0]
        assert action["state"] == "awaiting_confirmation"
        assert action["proposal"]["action_type"] == "cancel_order"
        assert "result_json" not in response.text
    finally:
        app.dependency_overrides.clear()
