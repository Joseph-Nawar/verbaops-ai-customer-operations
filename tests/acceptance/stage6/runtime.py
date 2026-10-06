"""Deterministic multi-principal runtime used only by the Stage 6 acceptance stack."""

from uuid import UUID

from fastapi import FastAPI

from verbaops.api.app import create_app
from verbaops.auth.context import Role, TrustedContext
from verbaops.auth.development import DevelopmentAuthProvider
from verbaops.auth.provider import OpaqueCredential
from verbaops.config.settings import Environment, Settings


def create_acceptance_app() -> FastAPI:
    """Compose the real application with test-only trusted identity mappings."""

    settings = Settings()
    if settings.environment not in (Environment.DEVELOPMENT, Environment.TEST):
        raise RuntimeError("Stage 6 acceptance requires the deterministic test environment")

    customer = TrustedContext(
        principal_id=settings.auth.development_principal_id,
        tenant_id=settings.auth.development_tenant_id,
        customer_id=settings.auth.development_customer_id,
        roles=frozenset({Role.CUSTOMER}),
    )
    supervisor = TrustedContext(
        principal_id=UUID("10000000-0000-0000-0000-000000000099"),
        tenant_id=settings.auth.development_tenant_id,
        customer_id=None,
        roles=frozenset({Role.SUPPORT_SUPERVISOR}),
    )
    self_approver = customer.model_copy(
        update={"roles": frozenset({Role.CUSTOMER, Role.SUPPORT_SUPERVISOR})}
    )
    other_customer = customer.model_copy(
        update={
            "principal_id": UUID("10000000-0000-0000-0000-000000000098"),
            "customer_id": UUID("1e6f81a6-e717-58fa-9418-00f7e268538a"),
        }
    )
    provider = DevelopmentAuthProvider(
        {
            OpaqueCredential(settings.auth.development_token.get_secret_value()): customer,
            OpaqueCredential("stage6-supervisor-token"): supervisor,
            OpaqueCredential("stage6-self-approver-token"): self_approver,
            OpaqueCredential("stage6-other-customer-token"): other_customer,
        },
        environment=settings.environment,
    )
    return create_app(settings=settings, auth_provider=provider)
