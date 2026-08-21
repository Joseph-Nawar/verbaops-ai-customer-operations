"""Immutable canonical seed configuration."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, tzinfo

DEFAULT_SEED = 20260821
DEFAULT_AS_OF = date(2026, 8, 21)


@dataclass(frozen=True, slots=True)
class SeedConfig:
    """Inputs that fully determine a generated dataset."""

    seed: int = DEFAULT_SEED
    as_of: date = DEFAULT_AS_OF

    @property
    def utc(self) -> tzinfo:
        return UTC

    @property
    def anchor(self) -> datetime:
        return datetime.combine(self.as_of, time(12, 0), tzinfo=UTC)


def parse_as_of(value: str) -> date:
    """Parse the ISO date accepted by the CLI."""

    return date.fromisoformat(value)
