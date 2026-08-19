"""Behavioral tests for the immutable trusted identity context."""

from collections.abc import Callable
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from relayai.auth.context import Role, TrustedContext

PRINCIPAL_ID = UUID("00000000-0000-0000-0000-000000000001")
TENANT_ID = UUID("00000000-0000-0000-0000-000000000002")
CUSTOMER_ID = UUID("00000000-0000-0000-0000-000000000003")


def make_context(*, customer_id: UUID | None = CUSTOMER_ID) -> TrustedContext:
    return TrustedContext(
        principal_id=PRINCIPAL_ID,
        tenant_id=TENANT_ID,
        customer_id=customer_id,
        roles=frozenset({Role.CUSTOMER}),
    )


def test_valid_trusted_context_is_constructed() -> None:
    context = make_context()

    assert context.principal_id == PRINCIPAL_ID
    assert context.tenant_id == TENANT_ID
    assert context.customer_id == CUSTOMER_ID
    assert context.roles == frozenset({Role.CUSTOMER})


def test_customer_id_is_optional() -> None:
    assert make_context(customer_id=None).customer_id is None


def test_all_supported_roles_are_typed_values() -> None:
    context = TrustedContext(
        principal_id=PRINCIPAL_ID,
        tenant_id=TENANT_ID,
        customer_id=None,
        roles=frozenset(Role),
    )

    assert context.roles == frozenset(
        {
            Role.CUSTOMER,
            Role.SUPPORT_AGENT,
            Role.SUPPORT_SUPERVISOR,
            Role.TENANT_ADMIN,
        }
    )


def test_extra_identity_fields_are_rejected() -> None:
    construct = cast(Callable[..., TrustedContext], TrustedContext)

    with pytest.raises(ValidationError):
        construct(
            principal_id=PRINCIPAL_ID,
            tenant_id=TENANT_ID,
            customer_id=None,
            roles=frozenset({Role.CUSTOMER}),
            request_id="not-part-of-trusted-context",
        )


def test_trusted_context_is_immutable() -> None:
    context = make_context()

    with pytest.raises(ValidationError):
        context.tenant_id = UUID("00000000-0000-0000-0000-000000000004")
