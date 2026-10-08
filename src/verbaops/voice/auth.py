"""Dedicated constant-time authentication for the internal Voice Worker."""

from dataclasses import dataclass
from secrets import compare_digest
from typing import Literal

from pydantic import SecretStr

from verbaops.auth.provider import AuthenticationError, OpaqueCredential


@dataclass(frozen=True, slots=True)
class VoiceWorkerContext:
    """Fixed service identity; it carries no tenant, customer, principal, or roles."""

    service_name: Literal["voice_worker"] = "voice_worker"


def authenticate_worker(
    credential: OpaqueCredential,
    *,
    expected_token: SecretStr | str,
) -> VoiceWorkerContext:
    """Authenticate only the configured service credential with constant-time comparison."""

    expected = (
        expected_token.get_secret_value()
        if isinstance(expected_token, SecretStr)
        else expected_token
    )
    if not compare_digest(str(credential), expected):
        raise AuthenticationError("authentication failed")
    return VoiceWorkerContext()
