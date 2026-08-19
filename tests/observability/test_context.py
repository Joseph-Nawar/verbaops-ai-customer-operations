"""ContextVar request metadata tests."""

from uuid import UUID

from relayai.observability.context import (
    bind_request_context,
    bind_tenant_id,
    clear_request_context,
    get_request_context,
)


def test_context_binding_and_cleanup_are_explicit() -> None:
    request_id = UUID("40000000-0000-0000-0000-000000000001")
    correlation_id = UUID("40000000-0000-0000-0000-000000000002")
    tenant_id = UUID("40000000-0000-0000-0000-000000000003")

    bind_request_context(request_id, correlation_id)
    bind_tenant_id(tenant_id)

    context = get_request_context()
    assert context.request_id == request_id
    assert context.correlation_id == correlation_id
    assert context.tenant_id == tenant_id
    assert context.conversation_id is None

    clear_request_context()

    assert get_request_context().request_id is None
    assert get_request_context().correlation_id is None
    assert get_request_context().tenant_id is None
    assert get_request_context().conversation_id is None
