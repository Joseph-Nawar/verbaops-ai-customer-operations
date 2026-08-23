"""Shared run-level UTC timestamp handling for black-box acceptance."""

from datetime import UTC, datetime


def serialize_acceptance_as_of(value: datetime) -> str:
    """Return a second-precision UTC timestamp suitable for Compose/env files."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ACCEPTANCE_AS_OF must include a timezone")
    normalized = value.astimezone(UTC).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def parse_acceptance_as_of(value: str) -> datetime:
    """Parse an explicit acceptance timestamp and normalize it to UTC seconds."""
    normalized = value.strip()
    if not normalized:
        raise ValueError("ACCEPTANCE_AS_OF must be a non-blank ISO-8601 timestamp")
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError("ACCEPTANCE_AS_OF must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("ACCEPTANCE_AS_OF must include a timezone")
    return parsed.astimezone(UTC).replace(microsecond=0)
