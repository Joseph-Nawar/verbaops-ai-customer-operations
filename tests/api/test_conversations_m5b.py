from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest
from fastapi import FastAPI

from tests.api.conftest import request
from tests.api.test_conversations_m3e import (
    FakeAgentRuntime,
    FakeConversationService,
    _message,
    _result,
)
from verbaops.api.dependencies import get_agent_runtime, get_conversation_service
from verbaops.conversations.domain import CitationRecord


def citation(message_id: object) -> CitationRecord:
    return CitationRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        message_id=message_id,  # type: ignore[arg-type]
        retrieval_invocation_id=uuid4(),
        chunk_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        citation_ordinal=1,
        evidence_key="K1",
        document_title="Returns Policy",
        document_slug="returns-policy",
        document_version="2026.1",
        section="Return Window",
        effective_date=date(2026, 1, 1),
        created_at=_result().assistant_message.created_at,
    )


@pytest.mark.asyncio
async def test_post_and_get_conversation_expose_persisted_public_citations(app: FastAPI) -> None:
    service = FakeConversationService()
    assistant = _message("assistant", 2, "Return within 30 days [1]")
    stored_citation = citation(assistant.id)
    assistant = replace(assistant, citations=(stored_citation,))
    service.messages = [_message("user", 1, "What is the return window?"), assistant]
    result = _result()
    result = replace(
        result,
        assistant_message=assistant,
        assistant_message_id=assistant.id,
        content=assistant.content,
    )
    app.dependency_overrides[get_conversation_service] = lambda: service
    app.dependency_overrides[get_agent_runtime] = lambda: FakeAgentRuntime(result)
    try:
        headers = {"Authorization": "Bearer opaque-test-credential"}
        sent = await request(
            app,
            "POST",
            f"/v1/conversations/{service.conversation.id}/messages",
            headers=headers,
            json={"content": "What is the return window?"},
        )
        assert sent.status_code == 200
        assert sent.json()["assistant_message"]["citations"] == [
            {
                "number": 1,
                "document": "Returns Policy",
                "section": "Return Window",
                "version": "2026.1",
                "effective_date": "2026-01-01",
            }
        ]

        fetched = await request(
            app,
            "GET",
            f"/v1/conversations/{service.conversation.id}",
            headers=headers,
        )
        assert fetched.status_code == 200
        assert (
            fetched.json()["messages"][-1]["citations"]
            == sent.json()["assistant_message"]["citations"]
        )
        assert "document_slug" not in fetched.text
        assert "version_id" not in fetched.text
    finally:
        app.dependency_overrides.clear()
