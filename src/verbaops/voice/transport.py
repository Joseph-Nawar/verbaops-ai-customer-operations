"""Minimal transport-token protocol shared by the session service and issuer."""

from datetime import timedelta
from typing import Protocol


class LiveKitTokenIssuer(Protocol):
    """Mint only a short-lived customer browser room credential."""

    async def mint_customer_token(
        self,
        *,
        room_identity: str,
        participant_identity: str,
        ttl: timedelta,
    ) -> str:
        """Return a signed token without persisting or logging it."""
