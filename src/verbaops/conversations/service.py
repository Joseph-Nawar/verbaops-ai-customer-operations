"""Short-transaction lifecycle service for future agent turns."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verbaops.conversations.domain import (
    AgentRunRecord,
    ConversationRecord,
    ConversationScope,
    MessagePage,
    MessageRecord,
    ModelCallRecord,
    ToolInvocationRecord,
    TurnCompletion,
    TurnStart,
)
from verbaops.conversations.errors import ConversationBusyError
from verbaops.conversations.repository import ConversationRepository
from verbaops.llm.models import ResponseMetadata
from verbaops.retrieval.models import RetrievalEvidence


class ConversationService:
    """Own one committed database transaction per lifecycle operation."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        stale_after: timedelta = timedelta(minutes=15),
    ) -> None:
        self._session_factory = session_factory
        self._stale_after = stale_after

    async def create_conversation(
        self, scope: ConversationScope, customer_id: UUID | None = None
    ) -> ConversationRecord:
        async with self._session_factory() as session, session.begin():
            return await ConversationRepository(session).create_conversation(scope, customer_id)

    async def get_conversation(
        self, scope: ConversationScope, conversation_id: UUID
    ) -> ConversationRecord:
        async with self._session_factory() as session, session.begin():
            return await ConversationRepository(session).get_conversation(scope, conversation_id)

    async def list_messages(
        self, scope: ConversationScope, conversation_id: UUID
    ) -> list[MessageRecord]:
        async with self._session_factory() as session, session.begin():
            return await ConversationRepository(session).list_messages(scope, conversation_id)

    async def list_messages_page(
        self,
        scope: ConversationScope,
        conversation_id: UUID,
        *,
        limit: int,
        before_sequence: int | None = None,
    ) -> MessagePage:
        """Return a bounded scoped page without holding a session open."""

        async with self._session_factory() as session, session.begin():
            return await ConversationRepository(session).list_messages_page(
                scope,
                conversation_id,
                limit=limit,
                before_sequence=before_sequence,
            )

    async def start_turn(
        self,
        scope: ConversationScope,
        conversation_id: UUID,
        content: str,
        *,
        graph_version: str,
        prompt_version: str,
        tool_schema_version: str,
    ) -> TurnStart:
        async with self._session_factory() as session:
            try:
                async with session.begin():
                    conversation, user_message, agent_run = await ConversationRepository(
                        session
                    ).start_turn(
                        scope,
                        conversation_id,
                        content,
                        graph_version=graph_version,
                        prompt_version=prompt_version,
                        tool_schema_version=tool_schema_version,
                        stale_after=self._stale_after,
                    )
            except IntegrityError as error:
                if "uq_agent_runs_one_running_per_conversation" in str(error):
                    raise ConversationBusyError() from None
                raise
        return TurnStart(conversation, user_message, agent_run)

    async def append_model_call(
        self,
        scope: ConversationScope,
        conversation_id: UUID,
        agent_run_id: UUID,
        metadata: ResponseMetadata,
        *,
        status: str = "succeeded",
        error_code: str | None = None,
    ) -> ModelCallRecord:
        async with self._session_factory() as session, session.begin():
            return await ConversationRepository(session).append_model_call(
                scope,
                conversation_id,
                agent_run_id,
                metadata,
                status=status,
                error_code=error_code,
            )

    async def append_tool_invocation(
        self,
        scope: ConversationScope,
        conversation_id: UUID,
        agent_run_id: UUID,
        *,
        tool_call_id: str,
        tool_name: str,
        risk_level: str,
        arguments: dict[str, Any],
        status: str = "proposed",
        result: Any | None = None,
        latency_ms: float | None = None,
        error_code: str | None = None,
        completed_at: datetime | None = None,
    ) -> ToolInvocationRecord:
        async with self._session_factory() as session, session.begin():
            return await ConversationRepository(session).append_tool_invocation(
                scope,
                conversation_id,
                agent_run_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                risk_level=risk_level,
                arguments=arguments,
                status=status,
                result=result,
                latency_ms=latency_ms,
                error_code=error_code,
                completed_at=completed_at,
            )

    async def complete_turn(
        self,
        scope: ConversationScope,
        conversation_id: UUID,
        agent_run_id: UUID,
        content: str,
        *,
        retrieval_invocation_id: UUID | None = None,
        citations: Sequence[RetrievalEvidence] = (),
    ) -> TurnCompletion:
        async with self._session_factory() as session, session.begin():
            assistant_message, agent_run = await ConversationRepository(session).complete_turn(
                scope,
                conversation_id,
                agent_run_id,
                content,
                retrieval_invocation_id=retrieval_invocation_id,
                citations=citations,
            )
        return TurnCompletion(assistant_message=assistant_message, agent_run=agent_run)

    async def fail_turn(
        self, scope: ConversationScope, conversation_id: UUID, agent_run_id: UUID, error_code: str
    ) -> AgentRunRecord:
        async with self._session_factory() as session, session.begin():
            return await ConversationRepository(session).fail_turn(
                scope, conversation_id, agent_run_id, error_code
            )
