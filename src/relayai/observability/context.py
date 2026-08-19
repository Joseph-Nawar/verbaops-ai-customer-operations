"""Request-local metadata stored in ContextVars."""

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Current request metadata visible to application logging."""

    request_id: UUID | None
    correlation_id: UUID | None
    tenant_id: UUID | None
    conversation_id: UUID | None


request_id_context: ContextVar[UUID | None] = ContextVar(
    "relayai_request_id",
    default=None,
)
correlation_id_context: ContextVar[UUID | None] = ContextVar(
    "relayai_correlation_id",
    default=None,
)
tenant_id_context: ContextVar[UUID | None] = ContextVar(
    "relayai_tenant_id",
    default=None,
)
conversation_id_context: ContextVar[UUID | None] = ContextVar(
    "relayai_conversation_id",
    default=None,
)


def bind_request_context(request_id: UUID, correlation_id: UUID) -> None:
    """Bind server-established request and correlation identifiers."""

    request_id_context.set(request_id)
    correlation_id_context.set(correlation_id)
    conversation_id_context.set(None)


def bind_tenant_id(tenant_id: UUID) -> None:
    """Bind tenant identity only after successful trusted authentication."""

    tenant_id_context.set(tenant_id)


def get_request_context() -> RequestContext:
    """Return the current request-local metadata snapshot."""

    return RequestContext(
        request_id=request_id_context.get(),
        correlation_id=correlation_id_context.get(),
        tenant_id=tenant_id_context.get(),
        conversation_id=conversation_id_context.get(),
    )


def clear_request_context() -> None:
    """Clear all request-local metadata at the end of a request."""

    request_id_context.set(None)
    correlation_id_context.set(None)
    tenant_id_context.set(None)
    conversation_id_context.set(None)
