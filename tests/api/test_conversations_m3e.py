"""RED tests for the M3E authenticated conversation API."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI

from tests.api.conftest import build_context, request
from verbaops.agent.errors import (
    AgentBudgetExceededError,
    AgentProtocolError,
    AgentUnavailableError,
)
from verbaops.agent.runtime import AgentTurnResult
from verbaops.api.dependencies import get_agent_runtime, get_conversation_service
from verbaops.auth.context import TrustedContext
from verbaops.conversations.domain import (
    AgentRunRecord,
    ConversationRecord,
    ConversationScope,
    MessageRecord,
)
from verbaops.conversations.errors import ConversationBusyError, ConversationNotFoundError

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
CONVERSATION_ID = UUID("80000000-0000-0000-0000-000000000001")


def _conversation() -> ConversationRecord:
    trusted = build_context()
    return ConversationRecord(
        id=CONVERSATION_ID,
        tenant_id=trusted.tenant_id,
        principal_id=trusted.principal_id,
        customer_id=trusted.customer_id,
        created_at=NOW,
        updated_at=NOW,
    )


def _message(role: str, sequence: int, content: str) -> MessageRecord:
    return MessageRecord(
        id=uuid4(),
        conversation_id=CONVERSATION_ID,
        sequence=sequence,
        role=role,
        content=content,
        created_at=NOW,
    )


class FakeConversationService:
    def __init__(self, *, contextless: bool = False) -> None:
        self.contextless = contextless
        self.conversation = _conversation()
        self.messages = [_message("user", 1, "hello"), _message("assistant", 2, "hi")]
        self.created_scope: ConversationScope | None = None
        self.created_customer_id: UUID | None = None
        self.page_calls: list[tuple[int, int | None]] = []

    async def create_conversation(
        self, scope: ConversationScope, customer_id: UUID
    ) -> ConversationRecord:
        self.created_scope = scope
        self.created_customer_id = customer_id
        return self.conversation

    async def get_conversation(
        self, scope: ConversationScope, conversation_id: UUID
    ) -> ConversationRecord:
        if conversation_id != self.conversation.id:
            raise ConversationNotFoundError()
        return self.conversation

    async def list_messages_page(
        self,
        scope: ConversationScope,
        conversation_id: UUID,
        *,
        limit: int,
        before_sequence: int | None,
    ) -> object:
        if conversation_id != self.conversation.id:
            raise ConversationNotFoundError()
        from verbaops.conversations.domain import MessagePage

        messages = self.messages
        if before_sequence is not None:
            messages = [message for message in messages if message.sequence < before_sequence]
        self.page_calls.append((limit, before_sequence))
        descending = list(reversed(messages))
        page = list(reversed(descending[:limit]))
        has_more = len(descending) > limit
        return MessagePage(
            messages=tuple(page),
            has_more=has_more,
            next_before_sequence=page[0].sequence if has_more else None,
        )


class FakeAgentRuntime:
    def __init__(self, result: AgentTurnResult | Exception) -> None:
        self.result = result
        self.arguments: tuple[ConversationScope, UUID, UUID, str] | None = None

    async def run_turn(
        self, scope: ConversationScope, conversation_id: UUID, customer_id: UUID, content: str
    ) -> AgentTurnResult:
        self.arguments = (scope, conversation_id, customer_id, content)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _result() -> AgentTurnResult:
    user = _message("user", 1, "Where is my order?")
    assistant = _message("assistant", 2, "Please provide your order ID.")
    run_id = UUID("80000000-0000-0000-0000-000000000002")
    return AgentTurnResult(
        conversation_id=CONVERSATION_ID,
        agent_run_id=run_id,
        assistant_message_id=assistant.id,
        content=assistant.content,
        agent_run=AgentRunRecord(
            id=run_id,
            conversation_id=CONVERSATION_ID,
            user_message_id=user.id,
            assistant_message_id=assistant.id,
            status="completed",
            graph_version="text-agent-v1",
            prompt_version="text-agent-system-v1",
            tool_schema_version="commerce-read-tools-v1",
            started_at=NOW,
            completed_at=NOW,
            error_code=None,
        ),
        user_message=user,
        assistant_message=assistant,
    )


@pytest.mark.asyncio
async def test_all_conversation_routes_require_bearer_auth(app: FastAPI) -> None:
    for method, path, body in (
        ("POST", "/v1/conversations", {}),
        ("POST", f"/v1/conversations/{CONVERSATION_ID}/messages", {"content": "hello"}),
        ("GET", f"/v1/conversations/{CONVERSATION_ID}", None),
    ):
        response = await request(app, method, path, json=body, lifespan=False)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authentication_failed"


@pytest.mark.asyncio
async def test_create_and_message_responses_use_trusted_identity_only(
    app: FastAPI, trusted_context: TrustedContext
) -> None:
    service = FakeConversationService()
    runtime = FakeAgentRuntime(_result())
    app.dependency_overrides[get_conversation_service] = lambda: service
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    try:
        headers = {"Authorization": "Bearer opaque-test-credential"}
        created = await request(app, "POST", "/v1/conversations", headers=headers, json={})
        assert created.status_code == 201
        assert created.json() == {
            "conversation_id": str(CONVERSATION_ID),
            "created_at": NOW.isoformat().replace("+00:00", "Z"),
            "updated_at": NOW.isoformat().replace("+00:00", "Z"),
        }
        assert service.created_scope is not None
        assert service.created_scope.tenant_id == trusted_context.tenant_id
        assert service.created_scope.principal_id == trusted_context.principal_id
        assert service.created_customer_id == trusted_context.customer_id

        sent = await request(
            app,
            "POST",
            f"/v1/conversations/{CONVERSATION_ID}/messages",
            headers=headers,
            json={"content": "Where is my order?"},
        )
        assert sent.status_code == 200
        assert set(sent.json()) == {
            "conversation_id",
            "run_id",
            "user_message",
            "assistant_message",
        }
        assert sent.json()["assistant_message"]["content"] == "Please provide your order ID."
        assert "tenant_id" not in sent.text
        assert runtime.arguments is not None
        assert runtime.arguments[2] == trusted_context.customer_id
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_strict_inputs_and_customer_context_error(
    app: FastAPI, trusted_context: TrustedContext
) -> None:
    service = FakeConversationService()
    app.dependency_overrides[get_conversation_service] = lambda: service
    app.dependency_overrides[get_agent_runtime] = lambda: FakeAgentRuntime(_result())
    try:
        headers = {"Authorization": "Bearer opaque-test-credential"}
        extra = await request(
            app,
            "POST",
            "/v1/conversations",
            headers=headers,
            json={"customer_id": str(trusted_context.customer_id)},
        )
        assert extra.status_code == 422

        invalid_message = await request(
            app,
            "POST",
            f"/v1/conversations/{CONVERSATION_ID}/messages",
            headers=headers,
            json={"content": " "},
        )
        assert invalid_message.status_code == 422
        too_long = await request(
            app,
            "POST",
            f"/v1/conversations/{CONVERSATION_ID}/messages",
            headers=headers,
            json={"content": "x" * 8001},
        )
        assert too_long.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_missing_customer_context_is_forbidden(app: FastAPI) -> None:
    from tests.api.conftest import build_provider
    from verbaops.api.app import create_app

    app = create_app(
        settings=app.state.verbaops_dependencies.settings,
        auth_provider=build_provider(build_context(customer_id=None)),
    )
    service = FakeConversationService(contextless=True)
    app.dependency_overrides[get_conversation_service] = lambda: service
    try:
        response = await request(
            app,
            "POST",
            "/v1/conversations",
            headers={"Authorization": "Bearer opaque-test-credential"},
            json={},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "customer_context_required"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ConversationNotFoundError(), 404, "conversation_not_found"),
        (ConversationBusyError(), 409, "conversation_busy"),
        (AgentUnavailableError(), 503, "agent_unavailable"),
        (AgentProtocolError(), 502, "agent_execution_failed"),
        (AgentBudgetExceededError(), 502, "agent_execution_failed"),
    ],
)
async def test_message_failures_use_safe_public_contract(
    app: FastAPI, error: Exception, status: int, code: str
) -> None:
    runtime = FakeAgentRuntime(error)
    app.dependency_overrides[get_conversation_service] = lambda: FakeConversationService()
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    try:
        response = await request(
            app,
            "POST",
            f"/v1/conversations/{CONVERSATION_ID}/messages",
            headers={"Authorization": "Bearer opaque-test-credential"},
            json={"content": "hello"},
        )
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert "secret" not in response.text.lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_is_scoped_and_paginates_customer_visible_messages(app: FastAPI) -> None:
    service = FakeConversationService()
    app.dependency_overrides[get_conversation_service] = lambda: service
    try:
        response = await request(
            app,
            "GET",
            f"/v1/conversations/{CONVERSATION_ID}?limit=1",
            headers={"Authorization": "Bearer opaque-test-credential"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert [message["role"] for message in payload["messages"]] == ["assistant"]
        assert payload["has_more"] is True
        assert payload["next_before_sequence"] == 2
        assert "agent_runs" not in payload
        assert "tool_invocations" not in payload

        older = await request(
            app,
            "GET",
            f"/v1/conversations/{CONVERSATION_ID}?limit=1&before_sequence=2",
            headers={"Authorization": "Bearer opaque-test-credential"},
        )
        assert older.status_code == 200
        assert [message["role"] for message in older.json()["messages"]] == ["user"]
        assert service.page_calls == [(1, None), (1, 2)]

        foreign = await request(
            app,
            "GET",
            f"/v1/conversations/{uuid4()}",
            headers={"Authorization": "Bearer opaque-test-credential"},
        )
        assert foreign.status_code == 404
        assert foreign.json()["error"]["code"] == "conversation_not_found"
    finally:
        app.dependency_overrides.clear()
