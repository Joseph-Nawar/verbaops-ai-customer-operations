"""Tests for secret-safe Commerce client errors."""

from verbaops.commerce.errors import (
    CommerceAuthenticationError,
    CommerceError,
    CommerceNotFoundError,
    CommerceProtocolError,
    CommerceTimeoutError,
    CommerceUnavailableError,
)


def test_commerce_errors_have_safe_stable_messages() -> None:
    errors = (
        CommerceError,
        CommerceAuthenticationError,
        CommerceNotFoundError,
        CommerceProtocolError,
        CommerceTimeoutError,
        CommerceUnavailableError,
    )

    for error_type in errors:
        error = error_type("Authorization: Bearer sentinel-secret raw backend body")
        rendered = f"{error!s} {error!r}"
        assert "sentinel-secret" not in rendered
        assert "Authorization" not in rendered
        assert "raw backend body" not in rendered
