"""Transaction-scoped repository operations for conversation persistence."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from verbaops.conversations.domain import (
    AgentRunRecord,
    ConversationRecord,
    ConversationScope,
    MessageRecord,
    ModelCallRecord,
    ToolInvocationRecord,
    model_call_fields,
)
from verbaops.conversations.errors import (
    ConversationBusyError,
    ConversationLifecycleError,
    ConversationNotFoundError,
)
from verbaops.conversations.persistence import (
    AgentRun,
    Conversation,
    Message,
    ModelCall,
    ToolInvocation,
)
from verbaops.llm.models import ResponseMetadata


def utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationRepository:
    """Repository whose callers own a short transaction around each operation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_conversation(
        self, scope: ConversationScope, customer_id: UUID | None = None
    ) -> ConversationRecord:
        conversation = Conversation(
            tenant_id=scope.tenant_id,
            principal_id=scope.principal_id,
            customer_id=customer_id,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self._session.add(conversation)
        await self._session.flush()
        return _conversation_record(conversation)

    async def get_conversation(
        self, scope: ConversationScope, conversation_id: UUID, *, for_update: bool = False
    ) -> ConversationRecord:
        conversation = await self._conversation(scope, conversation_id, for_update=for_update)
        return _conversation_record(conversation)

    async def list_messages(
        self, scope: ConversationScope, conversation_id: UUID
    ) -> list[MessageRecord]:
        await self._conversation(scope, conversation_id)
        result = await self._session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sequence)
        )
        return [_message_record(message) for message in result]

    async def start_turn(
        self,
        scope: ConversationScope,
        conversation_id: UUID,
        content: str,
        *,
        graph_version: str,
        prompt_version: str,
        tool_schema_version: str,
        stale_after: timedelta,
    ) -> tuple[ConversationRecord, MessageRecord, AgentRunRecord]:
        conversation = await self._conversation(scope, conversation_id, for_update=True)
        await self._recover_or_reject_running(conversation_id, stale_after)

        next_sequence = await self._next_message_sequence(conversation_id)
        message = Message(
            conversation_id=conversation_id,
            sequence=next_sequence,
            role="user",
            content=content,
            created_at=utc_now(),
        )
        self._session.add(message)
        await self._session.flush()

        run = AgentRun(
            conversation_id=conversation_id,
            user_message_id=message.id,
            status="running",
            graph_version=graph_version,
            prompt_version=prompt_version,
            tool_schema_version=tool_schema_version,
            started_at=utc_now(),
        )
        self._session.add(run)
        conversation.updated_at = utc_now()
        await self._session.flush()
        return _conversation_record(conversation), _message_record(message), _agent_run_record(run)

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
        run = await self._run(scope, conversation_id, agent_run_id, for_update=True)
        _require_running(run)
        sequence = await self._next_trace_sequence(ModelCall, agent_run_id)
        model_call = ModelCall(
            agent_run_id=agent_run_id,
            sequence=sequence,
            **model_call_fields(metadata),
            status=status,
            error_code=error_code,
            created_at=utc_now(),
        )
        self._session.add(model_call)
        await self._session.flush()
        return _model_call_record(model_call)

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
        run = await self._run(scope, conversation_id, agent_run_id, for_update=True)
        _require_running(run)
        sequence = await self._next_trace_sequence(ToolInvocation, agent_run_id)
        invocation = ToolInvocation(
            agent_run_id=agent_run_id,
            sequence=sequence,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            risk_level=risk_level,
            arguments_json=arguments,
            result_json=result,
            status=status,
            latency_ms=latency_ms,
            error_code=error_code,
            created_at=utc_now(),
            completed_at=completed_at,
        )
        self._session.add(invocation)
        await self._session.flush()
        return _tool_invocation_record(invocation)

    async def complete_turn(
        self, scope: ConversationScope, conversation_id: UUID, agent_run_id: UUID, content: str
    ) -> tuple[MessageRecord, AgentRunRecord]:
        conversation = await self._conversation(scope, conversation_id, for_update=True)
        run = await self._run(scope, conversation_id, agent_run_id, for_update=True)
        _require_running(run)
        message = Message(
            conversation_id=conversation_id,
            sequence=await self._next_message_sequence(conversation_id),
            role="assistant",
            content=content,
            created_at=utc_now(),
        )
        self._session.add(message)
        await self._session.flush()
        completed_at = utc_now()
        run.assistant_message_id = message.id
        run.status = "completed"
        run.completed_at = completed_at
        conversation.updated_at = completed_at
        await self._session.flush()
        return _message_record(message), _agent_run_record(run)

    async def fail_turn(
        self, scope: ConversationScope, conversation_id: UUID, agent_run_id: UUID, error_code: str
    ) -> AgentRunRecord:
        conversation = await self._conversation(scope, conversation_id, for_update=True)
        run = await self._run(scope, conversation_id, agent_run_id, for_update=True)
        _require_running(run)
        run.status = "failed"
        run.error_code = error_code
        run.completed_at = utc_now()
        conversation.updated_at = utc_now()
        await self._session.flush()
        return _agent_run_record(run)

    async def _conversation(
        self, scope: ConversationScope, conversation_id: UUID, *, for_update: bool = False
    ) -> Conversation:
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == scope.tenant_id,
            Conversation.principal_id == scope.principal_id,
        )
        if for_update:
            statement = statement.with_for_update()
        conversation = await self._session.scalar(statement)
        if conversation is None:
            raise ConversationNotFoundError()
        return conversation

    async def _run(
        self,
        scope: ConversationScope,
        conversation_id: UUID,
        agent_run_id: UUID,
        *,
        for_update: bool,
    ) -> AgentRun:
        statement = (
            select(AgentRun)
            .join(Conversation, Conversation.id == AgentRun.conversation_id)
            .where(
                AgentRun.id == agent_run_id,
                AgentRun.conversation_id == conversation_id,
                Conversation.tenant_id == scope.tenant_id,
                Conversation.principal_id == scope.principal_id,
            )
        )
        if for_update:
            statement = statement.with_for_update()
        run = await self._session.scalar(statement)
        if run is None:
            raise ConversationNotFoundError()
        return run

    async def _recover_or_reject_running(
        self, conversation_id: UUID, stale_after: timedelta
    ) -> None:
        cutoff = utc_now() - stale_after
        runs = await self._session.scalars(
            select(AgentRun)
            .where(AgentRun.conversation_id == conversation_id, AgentRun.status == "running")
            .with_for_update()
        )
        for run in runs:
            if run.started_at < cutoff:
                run.status = "failed"
                run.error_code = "stale_run_recovered"
                run.completed_at = utc_now()
            else:
                raise ConversationBusyError()
        await self._session.flush()

    async def _next_message_sequence(self, conversation_id: UUID) -> int:
        maximum = await self._session.scalar(
            select(func.max(Message.sequence)).where(Message.conversation_id == conversation_id)
        )
        return int(maximum or 0) + 1

    async def _next_trace_sequence(
        self, model: type[ModelCall] | type[ToolInvocation], run_id: UUID
    ) -> int:
        maximum = await self._session.scalar(
            select(func.max(model.sequence)).where(model.agent_run_id == run_id)
        )
        return int(maximum or 0) + 1


def _require_running(run: AgentRun) -> None:
    if run.status != "running":
        raise ConversationLifecycleError("agent run is not running")


def _conversation_record(row: Conversation) -> ConversationRecord:
    return ConversationRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        principal_id=row.principal_id,
        customer_id=row.customer_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _message_record(row: Message) -> MessageRecord:
    return MessageRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        sequence=row.sequence,
        role=row.role,
        content=row.content,
        created_at=row.created_at,
    )


def _agent_run_record(row: AgentRun) -> AgentRunRecord:
    return AgentRunRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        user_message_id=row.user_message_id,
        assistant_message_id=row.assistant_message_id,
        status=row.status,
        graph_version=row.graph_version,
        prompt_version=row.prompt_version,
        tool_schema_version=row.tool_schema_version,
        started_at=row.started_at,
        completed_at=row.completed_at,
        error_code=row.error_code,
    )


def _model_call_record(row: ModelCall) -> ModelCallRecord:
    return ModelCallRecord(
        id=row.id,
        agent_run_id=row.agent_run_id,
        sequence=row.sequence,
        capability_alias=row.capability_alias,
        gateway_request_id=row.gateway_request_id,
        gateway_model_id=row.gateway_model_id,
        model=row.model,
        provider=row.provider,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        total_tokens=row.total_tokens,
        latency_ms=row.latency_ms,
        cost_usd=row.cost_usd,
        finish_reason=row.finish_reason,
        status=row.status,
        error_code=row.error_code,
        created_at=row.created_at,
    )


def _tool_invocation_record(row: ToolInvocation) -> ToolInvocationRecord:
    return ToolInvocationRecord(
        id=row.id,
        agent_run_id=row.agent_run_id,
        sequence=row.sequence,
        tool_call_id=row.tool_call_id,
        tool_name=row.tool_name,
        risk_level=row.risk_level,
        arguments_json=row.arguments_json,
        result_json=row.result_json,
        status=row.status,
        latency_ms=row.latency_ms,
        error_code=row.error_code,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )
