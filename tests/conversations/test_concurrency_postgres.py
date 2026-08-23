"""M3B PostgreSQL concurrency contract tests."""

import asyncio
from uuid import UUID

import pytest

from verbaops.conversations.domain import ConversationScope
from verbaops.conversations.errors import ConversationBusyError
from verbaops.conversations.service import ConversationService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.concurrency,
    pytest.mark.m3b,
    pytest.mark.usefixtures("clean_verbaops_tables"),
]

SCOPE = ConversationScope(
    tenant_id=UUID("30000000-0000-0000-0000-000000000001"),
    principal_id=UUID("40000000-0000-0000-0000-000000000001"),
)


@pytest.mark.asyncio
async def test_concurrent_turn_attempts_allow_exactly_one_running_run(
    service: ConversationService,
) -> None:
    conversation = await service.create_conversation(SCOPE)

    async def attempt(content: str) -> object:
        try:
            return await service.start_turn(
                SCOPE,
                conversation.id,
                content,
                graph_version="g",
                prompt_version="p",
                tool_schema_version="t",
            )
        except Exception as error:
            return error

    first, second = await asyncio.gather(attempt("first"), attempt("second"))
    outcomes = (first, second)
    assert sum(not isinstance(result, Exception) for result in outcomes) == 1
    assert sum(isinstance(result, ConversationBusyError) for result in outcomes) == 1
