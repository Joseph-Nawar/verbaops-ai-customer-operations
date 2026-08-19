"""Trusted identity and authentication-provider abstractions."""

from relayai.auth.context import Role, TrustedContext
from relayai.auth.development import DevelopmentAuthProvider
from relayai.auth.provider import AuthenticationError, AuthProvider, OpaqueCredential

__all__ = [
    "AuthProvider",
    "AuthenticationError",
    "DevelopmentAuthProvider",
    "OpaqueCredential",
    "Role",
    "TrustedContext",
]
