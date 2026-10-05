"""Injectable clock so every run is reproducible (tests and --now)."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
UTC = timezone.utc


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock(Clock):
    def __init__(self, at: datetime):
        if at.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._at = at.astimezone(UTC)

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("timezone-aware datetime required")
        self._at = at.astimezone(UTC)


def parse_aware(value: str) -> datetime:
    """Parse ISO-8601; naive timestamps are rejected (fail-closed)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value!r}")
    return dt


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
