"""M3E scoped, bounded PostgreSQL message pagination tests."""

from uuid import uuid4

import pytest

from verbaops.conversations.domain import ConversationScope
from verbaops.conversations.service import ConversationService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.m3b,
    pytest.mark.usefixtures("clean_verbaops_tables"),
]


@pytest.mark.asyncio
async def test_scoped_message_pagination_is_bounded_and_chronological(
    service: ConversationService,
) -> None:
    scope = ConversationScope(tenant_id=uuid4(), principal_id=uuid4())
    conversation = await service.create_conversation(scope, uuid4())

    for index in range(5):
        turn = await service.start_turn(
            scope,
            conversation.id,
            f"question {index}",
            graph_version="text-agent-v1",
            prompt_version="text-agent-system-v1",
            tool_schema_version="commerce-read-tools-v1",
        )
        await service.complete_turn(scope, conversation.id, turn.agent_run.id, f"answer {index}")

    latest = await service.list_messages_page(scope, conversation.id, limit=2)
    assert [message.sequence for message in latest.messages] == [9, 10]
    assert latest.has_more is True
    assert latest.next_before_sequence == 9

    older = await service.list_messages_page(
        scope, conversation.id, limit=2, before_sequence=latest.next_before_sequence
    )
    assert [message.sequence for message in older.messages] == [7, 8]
    assert older.has_more is True
    assert older.next_before_sequence == 7
