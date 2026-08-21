"""Trusted identity and authentication-provider abstractions."""

from verbaops.auth.context import Role, TrustedContext
from verbaops.auth.development import DevelopmentAuthProvider
from verbaops.auth.provider import AuthenticationError, AuthProvider, OpaqueCredential

__all__ = [
    "AuthProvider",
    "AuthenticationError",
    "DevelopmentAuthProvider",
    "OpaqueCredential",
    "Role",
    "TrustedContext",
]
