"""JPX business days from the published holiday table.

A weekday that is not in this table is a business day only when that year is
present. A missing year stays unverified. This module does not invent a
publication clock.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

JST = timezone(timedelta(hours=9))

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "jpx_calendar"
HOLIDAYS = STORE / "holidays.json"
SOURCE_HTML = STORE / "source.html"
PAGE = "https://www.jpx.co.jp/corporate/about-jpx/calendar/index.html"
_ROW = re.compile(
    r"(\d{4})/(\d{2})/(\d{2})[^<]{0,20}</td[^>]*>\s*<td[^>]*>\s*([^<]+?)\s*</td>",
    re.I,
)


def parse_holiday_html(html: str) -> list[dict]:
    found = []
    seen = set()
    for year, month, day, name in _ROW.findall(html or ""):
        token = f"{year}-{month}-{day}"
        datetime.strptime(token, "%Y-%m-%d")
        label = re.sub(r"\s+", " ", name).strip()
        if not label or token in seen:
            continue
        seen.add(token)
        found.append({"date": token, "name": label})
    if len(found) < 15:
        raise ValueError("MALFORMED")
    return found


def save_calendar(html: str, seen_at: datetime) -> dict:
    holidays = parse_holiday_html(html)
    years = sorted({row["date"][:4] for row in holidays})
    payload = {
        "source": PAGE,
        "first_seen_at": seen_at.isoformat(),
        "published_at": None,
        "published_at_basis": None,
        "years": years,
        "holidays": holidays,
        "license_note": "JPXが公開する休業日一覧。出典URLを残す。売買条件には使わない。",
    }
    STORE.mkdir(parents=True, exist_ok=True)
    SOURCE_HTML.write_text(html, encoding="utf-8")
    HOLIDAYS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def load_holidays() -> dict:
    if not HOLIDAYS.exists():
        raise ValueError("CALENDAR_MISSING")
    payload = json.loads(HOLIDAYS.read_text(encoding="utf-8"))
    rows = payload.get("holidays")
    if not isinstance(rows, list) or not rows:
        raise ValueError("CALENDAR_MISSING")
    closed = {}
    for row in rows:
        token = row.get("date")
        datetime.strptime(token, "%Y-%m-%d")
        closed[token] = row.get("name") or ""
    years = {int(token[:4]) for token in closed}
    if not years:
        raise ValueError("CALENDAR_MISSING")
    return {"closed": closed, "years": years}


def _table():
    try:
        return load_holidays()
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None


def is_business_day(day: date, table: dict | None = None) -> bool | None:
    """True, False, or None when that year is not in the official table."""
    table = table if table is not None else _table()
    if table is None or day.year not in table["years"]:
        return None
    if day.weekday() >= 5:
        return False
    return day.isoformat() not in table["closed"]


def business_day_gap(session: date, observed: date, table: dict | None = None) -> int | None:
    """Count JPX business days after session and on or before observed."""
    if observed < session:
        return None
    table = table if table is not None else _table()
    if table is None:
        return None
    years = range(session.year, observed.year + 1)
    if any(year not in table["years"] for year in years):
        return None
    gap = 0
    day = session
    while day < observed:
        day += timedelta(days=1)
        opened = is_business_day(day, table)
        if opened is None:
            return None
        if opened:
            gap += 1
    return gap


def nth_business_day_after(start: date, count: int, table: dict | None = None) -> date | None:
    table = table if table is not None else _table()
    if table is None or count < 1:
        return None
    found = 0
    day = start
    for _ in range(80):
        day += timedelta(days=1)
        opened = is_business_day(day, table)
        if opened is None:
            return None
        if opened:
            found += 1
            if found == count:
                return day
    return None


def next_reported_week_end(period_end: date, table: dict | None = None) -> date | None:
    """Last business day of the calendar week after period_end's week."""
    table = table if table is not None else _table()
    if table is None:
        return None
    monday = period_end - timedelta(days=period_end.weekday())
    for shift in (7, 14):
        next_monday = monday + timedelta(days=shift)
        next_friday = next_monday + timedelta(days=4)
        day = next_friday
        while day >= next_monday:
            opened = is_business_day(day, table)
            if opened is None:
                return None
            if opened:
                return day
            day -= timedelta(days=1)
    return None


def verified_last_modified(header: str | None, session_date: str, first_seen_at: datetime) -> datetime | None:
    """Keep an HTTP timestamp only when it is a real clock inside the legal window.

    A missing header stays empty. The 15:30 schedule is not used as a substitute.
    """
    if not header or not str(header).strip():
        return None
    try:
        stamp = parsedate_to_datetime(str(header))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if stamp is None or stamp.tzinfo is None:
        return None
    seen = first_seen_at if first_seen_at.tzinfo else first_seen_at.replace(tzinfo=JST)
    session = datetime.strptime(session_date, "%Y-%m-%d").date()
    if stamp > seen or stamp.astimezone(JST).date() < session:
        return None
    return stamp.astimezone(JST)


def observed_date(observed_at: datetime) -> date:
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=JST)
    return observed_at.astimezone(JST).date()


def _base(session: date, observed: date) -> dict:
    return {
        "calendar_age_days": (observed - session).days,
        "business_day_gap": None,
        "freshness_basis": "jpx_business_day",
    }


def daily_freshness(session_date: str, observed_at: datetime) -> dict:
    """Latest daily print may be the previous business day. Holidays do not add age."""
    session = datetime.strptime(session_date, "%Y-%m-%d").date()
    observed = observed_date(observed_at)
    detail = _base(session, observed)
    if detail["calendar_age_days"] < 0:
        detail["freshness"] = "STALE"
        detail["freshness_basis"] = "future_session"
        return detail
    gap = business_day_gap(session, observed)
    detail["business_day_gap"] = gap
    if gap is None:
        detail["freshness"] = "CALENDAR_MISSING"
        detail["freshness_basis"] = "jpx_calendar_missing"
        return detail
    detail["freshness"] = "FRESH" if gap <= 1 else "STALE"
    return detail


def weekly_freshness(session_date: str, observed_at: datetime) -> dict:
    """A weekly file stays current until the next week's 4th business day.

    That due date is the exchange schedule. It is not a published_at.
    """
    session = datetime.strptime(session_date, "%Y-%m-%d").date()
    observed = observed_date(observed_at)
    detail = _base(session, observed)
    if detail["calendar_age_days"] < 0:
        detail["freshness"] = "STALE"
        detail["freshness_basis"] = "future_session"
        return detail
    table = _table()
    gap = business_day_gap(session, observed, table)
    detail["business_day_gap"] = gap
    week_end = next_reported_week_end(session, table)
    due = nth_business_day_after(week_end, 4, table) if week_end else None
    detail["next_publication_due_on"] = due.isoformat() if due else None
    detail["next_publication_due_basis"] = (
        "schedule_4th_business_day" if due else None
    )
    if gap is None or due is None:
        detail["freshness"] = "CALENDAR_MISSING"
        detail["freshness_basis"] = "jpx_calendar_missing"
        return detail
    detail["freshness"] = "FRESH" if observed < due else "STALE"
    return detail
