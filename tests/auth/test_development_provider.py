"""Behavioral tests for deterministic development authentication."""

from collections.abc import Callable
from typing import cast
from uuid import UUID

import pytest

from relayai.auth.context import Role, TrustedContext
from relayai.auth.development import DevelopmentAuthProvider
from relayai.auth.provider import AuthenticationError, OpaqueCredential
from relayai.config.settings import Environment

PRINCIPAL_ID = UUID("10000000-0000-0000-0000-000000000001")
TENANT_ID = UUID("10000000-0000-0000-0000-000000000002")
CUSTOMER_ID = UUID("10000000-0000-0000-0000-000000000003")


def make_context() -> TrustedContext:
    return TrustedContext(
        principal_id=PRINCIPAL_ID,
        tenant_id=TENANT_ID,
        customer_id=CUSTOMER_ID,
        roles=frozenset({Role.SUPPORT_AGENT}),
    )


def make_provider(environment: Environment) -> tuple[DevelopmentAuthProvider, TrustedContext]:
    context = make_context()
    provider = DevelopmentAuthProvider(
        {OpaqueCredential("opaque-development-token"): context},
        environment=environment,
    )
    return provider, context


@pytest.mark.parametrize("environment", [Environment.DEVELOPMENT, Environment.TEST])
def test_known_opaque_credential_returns_server_mapped_context(
    environment: Environment,
) -> None:
    provider, expected = make_provider(environment)

    result = provider.authenticate(OpaqueCredential("opaque-development-token"))

    assert result is expected


def test_unknown_credential_fails_without_disclosing_the_credential() -> None:
    provider, _ = make_provider(Environment.TEST)
    attempted = OpaqueCredential("secret-attempt-that-must-not-leak")

    with pytest.raises(AuthenticationError) as error:
        provider.authenticate(attempted)

    assert str(error.value) == "authentication failed"
    assert str(attempted) not in str(error.value)
    assert str(attempted) not in repr(error.value)


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("tenant_id", UUID("20000000-0000-0000-0000-000000000001")),
        ("customer_id", UUID("20000000-0000-0000-0000-000000000002")),
        ("roles", frozenset({Role.TENANT_ADMIN})),
    ],
)
def test_caller_identity_claims_are_not_authenticate_inputs(
    claim: str,
    value: object,
) -> None:
    provider, expected = make_provider(Environment.DEVELOPMENT)
    authenticate = cast(Callable[..., TrustedContext], provider.authenticate)

    with pytest.raises(TypeError):
        authenticate(OpaqueCredential("opaque-development-token"), **{claim: value})

    assert provider.authenticate(OpaqueCredential("opaque-development-token")) is expected


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
def test_development_provider_is_rejected_outside_development_and_test(
    environment: Environment,
) -> None:
    context = make_context()

    with pytest.raises(ValueError, match="development and test"):
        DevelopmentAuthProvider(
            {OpaqueCredential("opaque-development-token"): context},
            environment=environment,
        )
