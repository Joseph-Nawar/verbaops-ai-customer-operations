"""Bearer authentication and safe SQL LIKE helpers for NovaCommerce."""

import secrets

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from novacommerce.api.errors import APIError
from novacommerce.config.settings import Settings

service_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="NovaCommerceServiceBearer",
    description="NovaCommerce service-to-service bearer token",
)


def compare_service_token(presented: str, expected: str) -> bool:
    """Compare bearer values without a content-dependent early exit."""

    return secrets.compare_digest(presented, expected)


def escape_like_literal(value: str) -> str:
    """Escape PostgreSQL LIKE metacharacters for literal substring matching."""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _authentication_error() -> APIError:
    return APIError(
        401,
        "authentication_required",
        "Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def authenticate_service_token(
    settings: Settings, credentials: HTTPAuthorizationCredentials | None
) -> str:
    """Validate one bearer credential against application settings."""

    configured = settings.service_token
    if credentials is None or credentials.scheme.lower() != "bearer" or configured is None:
        raise _authentication_error()
    if not compare_service_token(credentials.credentials, configured.get_secret_value()):
        raise _authentication_error()
    return configured.get_secret_value()
