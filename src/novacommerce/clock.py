"""UTC clock abstraction for deterministic delivery-slot query defaults."""

from datetime import UTC, date, datetime, timedelta
from typing import Protocol


class UTCClock(Protocol):
    def today(self) -> date: ...


class SystemUTCClock:
    def today(self) -> date:
        return datetime.now(UTC).date()


class FixedUTCClock:
    def __init__(self, value: date) -> None:
        self._value = value

    def today(self) -> date:
        return self._value


def delivery_date_range(
    clock: UTCClock,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> tuple[date, date]:
    start = from_date or clock.today()
    end = to_date or (start + timedelta(days=14))
    if end < start:
        raise ValueError("to_date is before from_date")
    if (end - start).days > 31:
        raise ValueError("delivery date range exceeds 31 days")
    return start, end
