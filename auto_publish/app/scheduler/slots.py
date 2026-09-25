"""Timezone-aware baseline scheduling (spec §6).

Waves are defined in JST (the market clock, no DST). The audience-local time is
derived with zoneinfo, so a fixed JST slot correctly lands one hour earlier in
London/New York local time when those regions leave DST. The baseline is a
starting point only; TimingOptimizer (not in R1) will replace it once the
account has its own metrics.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..clock import JST, iso_utc
from ..errors import SchedulingError


@dataclass(frozen=True)
class Slot:
    platform: str
    wave: str
    publish_at: datetime  # aware, UTC
    audience_tz: str

    @property
    def publish_at_utc(self) -> str:
        return iso_utc(self.publish_at)

    @property
    def publish_at_jst(self) -> str:
        return self.publish_at.astimezone(JST).isoformat()

    @property
    def audience_local(self) -> str:
        local = self.publish_at.astimezone(ZoneInfo(self.audience_tz))
        return f"{local.isoformat()} ({local.tzname()})"


def _hm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def wave_window(session_date: str, wave: dict) -> tuple[datetime, datetime]:
    day = date.fromisoformat(session_date) + timedelta(days=int(wave["day_offset"]))

    def at(hhmm: str) -> datetime:
        h, m = _hm(hhmm)
        return datetime.combine(day, time(0, 0), tzinfo=JST) + timedelta(hours=h, minutes=m)

    return at(wave["start_jst"]), at(wave["end_jst"])


def compute_slot(
    *,
    platform: str,
    platform_cfg: dict,
    waves_cfg: dict,
    session_date: str,
    now: datetime,
    taken_utc: set[str],
    interval_minutes: int,
    min_lead_minutes: int,
) -> Slot:
    earliest = now + timedelta(minutes=min_lead_minutes)
    for wave_name in platform_cfg["waves"]:
        wave = waves_cfg[wave_name]
        start, end = wave_window(session_date, wave)
        t = start
        while t < end:
            if t >= earliest and iso_utc(t) not in taken_utc:
                return Slot(platform=platform, wave=wave_name, publish_at=t.astimezone(ZoneInfo("UTC")),
                            audience_tz=wave["audience_tz"])
            t += timedelta(minutes=interval_minutes)
    raise SchedulingError(
        f"{platform}: no free slot left in baseline waves {platform_cfg['waves']} for session {session_date}"
        " (window passed or full); refusing to post outside the planned window",
        code="SCHEDULE_WINDOW_MISSED",
    )
