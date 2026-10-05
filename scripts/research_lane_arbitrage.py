"""JPX daily arbitrage market total. Research reference only.

The workbook also lists trading participants. Those names are not stored, and
the workbook itself is not stored. trading_adoption stays false.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import jpx_business_calendar as jpx_calendar

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "research_lane" / "arbitrage_balance"
LATEST = STORE / "latest.json"
HISTORY = STORE / "history.jsonl"
PAGE = "https://www.jpx.co.jp/markets/statistics-equities/program/"
JST = timezone(timedelta(hours=9))
LICENSE_NOTE = (
    "JPX/東証が公開する裁定取引の市場合計。"
    "売買株数と現物ポジションの合計だけを保存する。"
    "個別の参加者名は保存しない。原票は残さない。"
    "出典URLを残す。売買条件には使わない。trading_adoption=false。"
)
_FILE = re.compile(r"(\d{2})(\d{2})(\d{2})\.xls[x]?$", re.I)
_SESSION_IN_TITLE = re.compile(r"（(\d{1,2})月(\d{1,2})日")
_STANDALONE_DATE = re.compile(r"^(20\d{2})年(\d{1,2})月(\d{1,2})日$")
_NEAR = re.compile(r"(20\d{2})年(\d{1,2})月限")
_RAW_SUFFIXES = {".xls", ".xlsx", ".pdf"}


def _text(value) -> str:
    if value is None:
        return ""
    try:
        import pandas as pd

        if not isinstance(value, (str, bytes)) and pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).replace("\n", "").strip()


def _compact(value) -> str:
    return re.sub(r"[\s\u3000]+", "", _text(value))


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        import pandas as pd

        if not isinstance(value, (str, bytes)) and pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")) or value != int(value):
            return None
        return int(value)
    if hasattr(value, "item") and not isinstance(value, str):
        try:
            return _number(value.item())
        except (TypeError, ValueError):
            return None
    token = _compact(value).replace(",", "").replace("，", "")
    sign = 1
    if token.startswith("▲"):
        sign = -1
        token = token[1:]
    if not re.fullmatch(r"-?\d+", token):
        return None
    return sign * int(token) if sign == 1 or not token.startswith("-") else None


def _rows(blob: bytes) -> list:
    import pandas as pd

    frame = pd.read_excel(BytesIO(blob), header=None)
    return [list(record) for record in frame.itertuples(index=False)]


def _joined(row) -> str:
    return "".join(_compact(cell) for cell in row)


def _find(rows, predicate, start: int, end: int | None = None) -> int:
    stop = len(rows) if end is None else end
    for index in range(start, stop):
        if predicate(rows[index]):
            return index
    raise ValueError("MALFORMED")


def _cols(row, label: str) -> list[int]:
    return [index for index, cell in enumerate(row) if label in _compact(cell)]


def _at(row, column: int):
    if column < 0 or column >= len(row):
        raise ValueError("MALFORMED")
    number = _number(row[column])
    if number is None:
        raise ValueError("MALFORMED")
    return number


def _title_month_day(row) -> tuple[int, int]:
    matched = _SESSION_IN_TITLE.search(_joined(row))
    if matched is None:
        raise ValueError("MALFORMED")
    return int(matched.group(1)), int(matched.group(2))


def session_from_url(url: str) -> str:
    matched = _FILE.search(url.split("?", 1)[0])
    if matched is None:
        raise ValueError("MALFORMED")
    year = 2000 + int(matched.group(1))
    session = f"{year:04d}-{int(matched.group(2)):02d}-{int(matched.group(3)):02d}"
    datetime.strptime(session, "%Y-%m-%d")
    return session


def _sheet_label_date(rows, stop: int) -> str | None:
    found = []
    for row in rows[:stop]:
        for cell in row:
            matched = _STANDALONE_DATE.fullmatch(_compact(cell))
            if matched is None:
                continue
            token = f"{int(matched.group(1)):04d}-{int(matched.group(2)):02d}-{int(matched.group(3)):02d}"
            datetime.strptime(token, "%Y-%m-%d")
            found.append(token)
    return found[0] if found else None


def _near_contract(rows, stop: int) -> str | None:
    for row in rows[:stop]:
        matched = _NEAR.search(_joined(row))
        if matched is not None:
            return f"{int(matched.group(1)):04d}-{int(matched.group(2)):02d}"
    return None


def _participant_names(rows, header: int, name_col: int) -> list[str]:
    names = []
    for row in rows[header + 1 :]:
        if name_col >= len(row):
            continue
        label = _compact(row[name_col])
        if label in {"", "-", "全社合計", "上位１５社計", "上位15社計"}:
            continue
        if "注" in label or "copyright" in label.lower():
            continue
        names.append(_text(row[name_col]))
    return names


def parse_arbitrage_workbook(blob: bytes, source_url: str) -> dict:
    """Read the market total. A participant name in the result is rejected."""
    if not blob:
        raise ValueError("MALFORMED")
    rows = _rows(blob)
    if len(rows) < 8:
        raise ValueError("MALFORMED")
    section_trade = _find(rows, lambda row: "現物株式の売買" in _joined(row) and "売買分" in _joined(row), 0)
    section_position = _find(rows, lambda row: "現物ポジション" in _joined(row) and "現在" in _joined(row), section_trade + 1)
    name_header = _find(rows, lambda row: _cols(row, "証券会社名"), section_position + 1)
    trade_month, trade_day = _title_month_day(rows[section_trade])
    position_month, position_day = _title_month_day(rows[section_position])
    session = session_from_url(source_url)
    session_date = datetime.strptime(session, "%Y-%m-%d")
    if (trade_month, trade_day) != (session_date.month, session_date.day):
        raise ValueError("MALFORMED")
    if (position_month, position_day) != (session_date.month, session_date.day):
        raise ValueError("MALFORMED")

    side_header = _find(rows, lambda row: _cols(row, "売付け") and _cols(row, "買付け"), section_trade + 1, section_position)
    share_row = _find(rows, lambda row: _cols(row, "株数"), side_header + 1, section_position)
    sell_col = _cols(rows[side_header], "売付け")
    buy_col = _cols(rows[side_header], "買付け")
    if len(sell_col) != 1 or len(buy_col) != 1:
        raise ValueError("MALFORMED")
    sell = _at(rows[share_row], sell_col[0])
    buy = _at(rows[share_row], buy_col[0])
    if min(sell, buy) < 0:
        raise ValueError("MALFORMED")

    tenor = _find(rows, lambda row: len(_cols(row, "当限")) >= 2 and len(_cols(row, "翌限以降")) >= 2 and len(_cols(row, "合計")) >= 2, section_position + 1, name_header)
    position_row = _find(rows, lambda row: _cols(row, "株数"), tenor + 1, name_header)
    change_row = _find(rows, lambda row: _cols(row, "前日比"), position_row, name_header)
    near_cols = _cols(rows[tenor], "当限")
    far_cols = _cols(rows[tenor], "翌限以降")
    total_cols = _cols(rows[tenor], "合計")
    if len(near_cols) < 2 or len(far_cols) < 2 or len(total_cols) < 2:
        raise ValueError("MALFORMED")
    short_near, long_near = _at(rows[position_row], near_cols[0]), _at(rows[position_row], near_cols[1])
    short_far, long_far = _at(rows[position_row], far_cols[0]), _at(rows[position_row], far_cols[1])
    short_total, long_total = _at(rows[position_row], total_cols[0]), _at(rows[position_row], total_cols[1])
    short_change_near, long_change_near = _at(rows[change_row], near_cols[0]), _at(rows[change_row], near_cols[1])
    short_change_far, long_change_far = _at(rows[change_row], far_cols[0]), _at(rows[change_row], far_cols[1])
    short_change_total, long_change_total = _at(rows[change_row], total_cols[0]), _at(rows[change_row], total_cols[1])
    if min(short_near, short_far, short_total, long_near, long_far, long_total) < 0:
        raise ValueError("MALFORMED")
    if short_near + short_far != short_total or long_near + long_far != long_total:
        raise ValueError("MALFORMED")
    if short_change_near + short_change_far != short_change_total:
        raise ValueError("MALFORMED")
    if long_change_near + long_change_far != long_change_total:
        raise ValueError("MALFORMED")

    sell_cols = _cols(rows[name_header], "売付株数")
    buy_cols = _cols(rows[name_header], "買付株数")
    name_cols = _cols(rows[name_header], "証券会社名")
    if len(sell_cols) != 1 or len(buy_cols) != 1 or len(name_cols) != 1:
        raise ValueError("MALFORMED")
    total_row = _find(rows, lambda row: any(_compact(cell) == "全社合計" for cell in row), name_header + 1)
    if _at(rows[total_row], sell_cols[0]) != sell or _at(rows[total_row], buy_cols[0]) != buy:
        raise ValueError("MALFORMED")
    names = _participant_names(rows, name_header, name_cols[0])
    label = _sheet_label_date(rows, name_header)
    if label is not None and label < session:
        raise ValueError("MALFORMED")
    parsed = {
        "session_date": session,
        "sell_shares_thousand": sell,
        "buy_shares_thousand": buy,
        "short_position_near_thousand": short_near,
        "short_position_far_thousand": short_far,
        "short_position_total_thousand": short_total,
        "long_position_near_thousand": long_near,
        "long_position_far_thousand": long_far,
        "long_position_total_thousand": long_total,
        "short_change_near_thousand": short_change_near,
        "short_change_far_thousand": short_change_far,
        "short_change_total_thousand": short_change_total,
        "long_change_near_thousand": long_change_near,
        "long_change_far_thousand": long_change_far,
        "long_change_total_thousand": long_change_total,
        "unit": "thousand_shares",
        "sheet_label_date": label,
        "near_contract_through": _near_contract(rows, name_header),
        "participant_names_retained": False,
        "raw_retained": False,
        "raw_retained_reason": "PARTICIPANT_NAMES_IN_SOURCE",
    }
    encoded = json.dumps(parsed, ensure_ascii=False)
    if "証券会社名" in encoded or "取引参加者別" in encoded:
        raise ValueError("MALFORMED")
    for name in names:
        if name and name in encoded:
            raise ValueError("MALFORMED")
    return parsed


def discover_workbooks(html: str) -> list[str]:
    links = re.findall(r"""href=["']([^"']+)["']""", html or "", flags=re.I)
    found = []
    for link in links:
        path = link.split("?", 1)[0].lower()
        if path.endswith(".xls") or path.endswith(".xlsx"):
            found.append(urljoin(PAGE, link))
    return list(dict.fromkeys(found))


def _fetch(url: str) -> tuple[bytes, str | None]:
    request = Request(url, headers={"User-Agent": "TradeCockpit-JPX-PointInTime/1.0"})
    with urlopen(request, timeout=30) as response:
        body = response.read()
        if getattr(response, "status", 200) != 200 or not body:
            raise ValueError("MISSING")
        return body, response.headers.get("Last-Modified")


def _clock_fields(session_date: str, seen_at: datetime, last_modified: str | None) -> dict:
    seen = seen_at.astimezone(JST)
    published = jpx_calendar.verified_last_modified(last_modified, session_date, seen)
    detail = jpx_calendar.daily_freshness(session_date, seen)
    return {
        "session_date": session_date,
        "first_seen_at": seen.isoformat(),
        "fetched_at": seen.isoformat(),
        "available_at": seen.isoformat(),
        "published_at": None if published is None else published.isoformat(),
        "published_at_basis": None if published is None else "http_last_modified",
        **detail,
    }


def build_record(blob: bytes, source_url: str, fetched_at: datetime, last_modified: str | None = None) -> dict:
    parsed = parse_arbitrage_workbook(blob, source_url)
    digest = hashlib.sha256(blob).hexdigest()
    clock = _clock_fields(parsed["session_date"], fetched_at, last_modified)
    research = parsed["long_position_total_thousand"] if clock["freshness"] == "FRESH" else None
    return {
        "id": "arbitrage_balance",
        "source": source_url,
        "source_page": PAGE,
        "license_note": LICENSE_NOTE,
        "sha256": digest,
        "source_sha256": digest,
        "trading_adoption": False,
        "real_submit_allowed": False,
        "counts_as_live_sample": False,
        "promotion_candidate": False,
        "source_stage": "OFFICIAL_PUBLIC",
        **parsed,
        **clock,
        "long_position_total_for_research": research,
    }


def _history_rows() -> list[dict]:
    if not HISTORY.exists():
        return []
    rows = []
    for line in HISTORY.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not row.get("session_date") or not row.get("sha256"):
            raise ValueError("MALFORMED")
        rows.append(row)
    return rows


def _no_raw_files() -> None:
    if not STORE.exists():
        return
    for path in STORE.rglob("*"):
        if path.is_file() and path.suffix.lower() in _RAW_SUFFIXES:
            raise ValueError("MALFORMED")


def write_store(records: list[dict]) -> dict:
    """Save totals only. The caller discards the workbook bytes after hashing."""
    if not records:
        raise ValueError("MISSING")
    _no_raw_files()
    STORE.mkdir(parents=True, exist_ok=True)
    incoming = {}
    for record in records:
        if record.get("raw_retained") is not False or record.get("participant_names_retained") is not False:
            raise ValueError("MALFORMED")
        if record.get("sha256") != record.get("source_sha256"):
            raise ValueError("MALFORMED")
        previous = incoming.get(record["session_date"])
        if previous is not None and previous["sha256"] != record["sha256"]:
            raise ValueError("MALFORMED")
        incoming[record["session_date"]] = record
    by_session = {row["session_date"]: row for row in _history_rows()}
    for session, record in incoming.items():
        previous = by_session.get(session)
        if previous and previous.get("sha256") == record["sha256"]:
            record = dict(record)
            seen = previous.get("first_seen_at") or previous["fetched_at"]
            verified_published = record.get("published_at")
            verified_basis = record.get("published_at_basis")
            record.update(_clock_fields(record["session_date"], datetime.fromisoformat(seen), None))
            record["first_seen_at"] = seen
            record["fetched_at"] = seen
            record["available_at"] = seen
            if previous.get("published_at"):
                record["published_at"] = previous["published_at"]
                record["published_at_basis"] = previous.get("published_at_basis")
            elif verified_published:
                record["published_at"] = verified_published
                record["published_at_basis"] = verified_basis
            detail = jpx_calendar.daily_freshness(record["session_date"], datetime.fromisoformat(seen))
            record.update(detail)
            record["long_position_total_for_research"] = (
                record["long_position_total_thousand"] if detail["freshness"] == "FRESH" else None
            )
        by_session[session] = record
    ordered = [by_session[key] for key in sorted(by_session)]
    HISTORY.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in ordered), encoding="utf-8")
    latest = ordered[-1]
    LATEST.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _no_raw_files()
    return latest


def fetch_and_store(now: datetime | None = None) -> dict:
    fetched_at = now or datetime.now(JST)
    html, _page_header = _fetch(PAGE)
    urls = discover_workbooks(html.decode("utf-8", "replace"))
    if not urls:
        raise ValueError("MISSING")
    records = []
    for url in urls:
        blob, last_modified = _fetch(url)
        records.append(build_record(blob, url, fetched_at, last_modified))
        del blob
    return write_store(records)


def _consistent(record: dict) -> None:
    required = ("source", "fetched_at", "available_at", "freshness", "license_note", "sha256", "session_date")
    if any(not record.get(key) for key in required):
        raise ValueError("MALFORMED")
    if record.get("trading_adoption") is not False or record.get("real_submit_allowed") is not False:
        raise ValueError("MALFORMED")
    if record.get("counts_as_live_sample") is not False or record.get("promotion_candidate") is not False:
        raise ValueError("MALFORMED")
    if record.get("source_stage") != "OFFICIAL_PUBLIC":
        raise ValueError("MALFORMED")
    if record.get("raw_retained") is not False or record.get("participant_names_retained") is not False:
        raise ValueError("MALFORMED")
    if record.get("sha256") != record.get("source_sha256") or not re.fullmatch(r"[0-9a-f]{64}", record.get("sha256") or ""):
        raise ValueError("MALFORMED")
    pairs = (
        ("short_position_near_thousand", "short_position_far_thousand", "short_position_total_thousand"),
        ("long_position_near_thousand", "long_position_far_thousand", "long_position_total_thousand"),
        ("short_change_near_thousand", "short_change_far_thousand", "short_change_total_thousand"),
        ("long_change_near_thousand", "long_change_far_thousand", "long_change_total_thousand"),
    )
    for left, right, total in pairs:
        values = [record.get(key) for key in (left, right, total)]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError("MALFORMED")
        if values[0] + values[1] != values[2]:
            raise ValueError("MALFORMED")
    for key in ("sell_shares_thousand", "buy_shares_thousand", "long_position_total_thousand"):
        value = record.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("MALFORMED")
    encoded = json.dumps(record, ensure_ascii=False)
    if "証券会社名" in encoded or "取引参加者別" in encoded:
        raise ValueError("MALFORMED")


def load_latest(now: datetime | None = None) -> dict:
    closed = {
        "id": "arbitrage_balance",
        "fetch_status": "NOT_FETCHED",
        "freshness": "MISSING",
        "long_position_total_thousand": None,
        "long_position_total_for_research": None,
        "trading_adoption": False,
        "real_submit_allowed": False,
        "counts_as_live_sample": False,
        "promotion_candidate": False,
        "published_at": None,
        "reason": "MISSING",
    }
    if not LATEST.exists():
        return closed
    try:
        _no_raw_files()
        record = json.loads(LATEST.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("MALFORMED")
        _consistent(record)
        seen = datetime.fromisoformat(record.get("first_seen_at") or record["fetched_at"])
        published = record.get("published_at")
        if published is not None:
            if record.get("published_at_basis") != "http_last_modified":
                raise ValueError("MALFORMED")
            stamp = datetime.fromisoformat(published)
            session = datetime.strptime(record["session_date"], "%Y-%m-%d").date()
            if stamp.tzinfo is None or stamp > seen or stamp.astimezone(JST).date() < session:
                raise ValueError("MALFORMED")
        for row in _history_rows():
            _consistent(row)
        clock = now or datetime.now(JST)
        at_fetch = jpx_calendar.daily_freshness(record["session_date"], seen)
        current = jpx_calendar.daily_freshness(record["session_date"], clock)
        record = dict(record)
        record["first_seen_at"] = seen.astimezone(JST).isoformat()
        record["published_at"] = published
        record["freshness_at_fetch"] = at_fetch["freshness"]
        record.update(current)
        record["fetch_status"] = "FETCHED"
        record["trading_adoption"] = False
        record["counts_as_live_sample"] = False
        record["promotion_candidate"] = False
        if current["freshness"] == "FRESH" and at_fetch["freshness"] == "FRESH":
            record["long_position_total_for_research"] = record["long_position_total_thousand"]
            record["reason"] = "FRESH"
        else:
            record["long_position_total_for_research"] = None
            record["reason"] = current["freshness"] if current["freshness"] != "FRESH" else "STALE"
        return record
    except (OSError, json.JSONDecodeError, ValueError, TypeError, ImportError, UnicodeError):
        closed["fetch_status"] = "FAIL_CLOSED"
        closed["freshness"] = "MALFORMED"
        closed["reason"] = "MALFORMED"
        return closed
