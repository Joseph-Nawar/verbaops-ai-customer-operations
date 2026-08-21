"""Deterministic development/test authentication provider."""

from collections.abc import Mapping
from types import MappingProxyType

from verbaops.auth.context import TrustedContext
from verbaops.auth.provider import AuthenticationError, OpaqueCredential
from verbaops.config.settings import Environment


class DevelopmentAuthProvider:
    """Resolve explicitly supplied development credentials from a trusted mapping."""

    def __init__(
        self,
        contexts: Mapping[OpaqueCredential, TrustedContext],
        *,
        environment: Environment,
    ) -> None:
        if environment not in (Environment.DEVELOPMENT, Environment.TEST):
            raise ValueError("DevelopmentAuthProvider is limited to development and test")
        self._contexts: Mapping[OpaqueCredential, TrustedContext] = MappingProxyType(dict(contexts))

    def authenticate(self, credential: OpaqueCredential, /) -> TrustedContext:
        """Return the trusted server-mapped context for an opaque credential."""

        try:
            return self._contexts[credential]
        except KeyError:
            raise AuthenticationError("authentication failed") from None
