"""Tokyo Stock Exchange trading-day calendar (fail-closed).

A date is a trading session only if ALL hold:
  * its year is in ``covered_years`` (otherwise we do not know -> CALENDAR_UNAVAILABLE)
  * it is Monday-Friday
  * it is not in ``closures`` (JPX published market holidays, incl. 12/31 and 1/1-1/3)
  * it is not in ``extra_closures`` (ad-hoc full-day halts added by the owner)

``session_overrides`` can change the close time of a specific session (e.g. a
shortened day); the default close comes from the calendar rules.

The calendar file is validated on load: bad dates, dates outside the covered
years, or a covered year missing its year-end / new-year closures make the whole
calendar unusable (CALENDAR_INVALID) -- nothing is guessed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, time, timedelta
from functools import lru_cache
from pathlib import Path

from ..errors import ValidationError
from ..hashing import sha256_bytes

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "tse_calendar.json"
SCHEMA = "auto_publish.tse_calendar.v1"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class CalendarError(ValidationError):
    code = "CALENDAR_INVALID"


@dataclass(frozen=True)
class DayStatus:
    date: str
    trading: bool
    reason: str               # "trading" | "weekend" | "closure:<name>" | "extra_closure:<name>"
    close_jst: str | None     # session close for trading days


@dataclass(frozen=True)
class TseCalendar:
    covered_years: frozenset
    closures: dict
    extra_closures: dict
    session_overrides: dict
    default_close: str
    sha256: str
    sources: tuple

    def _check_covered(self, d: date) -> None:
        if d.year not in self.covered_years:
            raise CalendarError(
                f"TSE calendar does not cover {d.year} (covered: {sorted(self.covered_years)}); refusing to guess",
                code="CALENDAR_UNAVAILABLE")

    def status(self, d: date | str) -> DayStatus:
        d = date.fromisoformat(d) if isinstance(d, str) else d
        self._check_covered(d)
        iso = d.isoformat()
        if d.weekday() >= 5:
            return DayStatus(iso, False, "weekend", None)
        if iso in self.closures:
            return DayStatus(iso, False, f"closure:{self.closures[iso]}", None)
        if iso in self.extra_closures:
            return DayStatus(iso, False, f"extra_closure:{self.extra_closures[iso]}", None)
        close = self.session_overrides.get(iso, {}).get("close_jst", self.default_close)
        return DayStatus(iso, True, "trading", close)

    def is_trading_day(self, d: date | str) -> bool:
        return self.status(d).trading

    def close_time(self, d: date | str) -> time:
        st = self.status(d)
        if not st.trading:
            raise CalendarError(f"{st.date} is not a trading session ({st.reason})", code="NOT_TRADING_DAY")
        hh, mm = map(int, st.close_jst.split(":"))
        return time(hh, mm)

    def require_trading_day(self, d: date | str) -> DayStatus:
        st = self.status(d)
        if not st.trading:
            raise CalendarError(f"{st.date} is not a TSE trading session ({st.reason})", code="NOT_TRADING_DAY",
                                details={"date": st.date, "reason": st.reason})
        return st

    def next_trading_day(self, d: date | str) -> date:
        d = date.fromisoformat(d) if isinstance(d, str) else d
        for _ in range(15):
            d += timedelta(days=1)
            if self.is_trading_day(d):
                return d
        raise CalendarError("no trading day within 15 days", code="CALENDAR_INVALID")

    def previous_trading_day(self, d: date | str) -> date:
        d = date.fromisoformat(d) if isinstance(d, str) else d
        for _ in range(15):
            d -= timedelta(days=1)
            if self.is_trading_day(d):
                return d
        raise CalendarError("no trading day within 15 days", code="CALENDAR_INVALID")


def _parse(raw: bytes) -> TseCalendar:
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalendarError(f"calendar is not valid UTF-8 JSON: {exc}") from exc
    if doc.get("schema") != SCHEMA:
        raise CalendarError(f"calendar schema must be {SCHEMA}")
    years = doc.get("covered_years")
    if not isinstance(years, list) or not years or not all(isinstance(y, int) for y in years):
        raise CalendarError("covered_years must be a non-empty list of years")
    rules = doc.get("rules") or {}
    default_close = rules.get("default_close_jst", "")
    if not _HHMM.match(str(default_close)):
        raise CalendarError("rules.default_close_jst must be HH:MM")

    def dated(mapping, name):
        if not isinstance(mapping, dict):
            raise CalendarError(f"{name} must be an object")
        out = {}
        for k, v in mapping.items():
            try:
                d = date.fromisoformat(k)
            except (TypeError, ValueError) as exc:
                raise CalendarError(f"{name}: bad date {k!r}") from exc
            if d.isoformat() != k:
                raise CalendarError(f"{name}: date must be YYYY-MM-DD ({k!r})")
            if d.year not in years:
                raise CalendarError(f"{name}: {k} is outside covered_years")
            out[k] = v
        return out

    closures = dated(doc.get("closures"), "closures")
    extra = dated(doc.get("extra_closures", {}), "extra_closures")
    overrides = dated(doc.get("session_overrides", {}), "session_overrides")
    for k, v in overrides.items():
        if not isinstance(v, dict) or not _HHMM.match(str(v.get("close_jst", ""))):
            raise CalendarError(f"session_overrides[{k}] needs close_jst HH:MM")
        if k in closures or k in extra:
            raise CalendarError(f"session_overrides[{k}] is also a closure")
    for y in years:
        for mmdd in rules.get("year_end_new_year_closed_mmdd", []):
            k = f"{y}-{mmdd}"
            if date.fromisoformat(k).weekday() < 5 and k not in closures:
                raise CalendarError(f"covered year {y} is missing the year-end/new-year closure {k}")
    return TseCalendar(frozenset(years), closures, extra, overrides, default_close, sha256_bytes(raw),
                       tuple(s.get("url", "") for s in doc.get("sources", [])))


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime_ns: int) -> TseCalendar:
    return _parse(Path(path).read_bytes())


def load_calendar(path: str | Path | None = None) -> TseCalendar:
    p = Path(path) if path else DEFAULT_PATH
    if not p.is_file():
        raise CalendarError(f"TSE calendar file missing: {p.name}", code="CALENDAR_UNAVAILABLE")
    return _load_cached(str(p.resolve()), p.stat().st_mtime_ns)
