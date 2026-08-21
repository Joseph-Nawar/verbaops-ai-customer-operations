"""Project-owned authentication provider contract."""

from typing import NewType, Protocol

from verbaops.auth.context import TrustedContext

OpaqueCredential = NewType("OpaqueCredential", str)


class AuthenticationError(Exception):
    """Raised when an opaque credential cannot be authenticated."""


class AuthProvider(Protocol):
    """Narrow provider contract that resolves credentials to trusted identity."""

    def authenticate(self, credential: OpaqueCredential, /) -> TrustedContext:
        """Return server-mapped identity for a valid credential."""
