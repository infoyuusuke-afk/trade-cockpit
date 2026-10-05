"""JPX weekly futures flow by investor type. Research reference only.

The value is the overseas Nikkei 225 futures trading-value net from the
official CSV. It is not a live entry input. trading_adoption stays false.
published_at is filled only from a verified HTTP timestamp.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import jpx_business_calendar as jpx_calendar

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "research_lane" / "investor_futures_flow"
RAW = STORE / "raw"
LATEST = STORE / "latest.json"
HISTORY = STORE / "history.jsonl"
PAGE = "https://www.jpx.co.jp/markets/statistics-derivatives/sector/index.html"
JST = timezone(timedelta(hours=9))
PRODUCTS = {"301": "Nikkei 225 Futures", "313": "Nikkei 225 mini", "331": "Nikkei 225 Micro Futures"}
INVESTOR_CODE = "60"
LICENSE_NOTE = (
    "JPX/大阪取引所が公開する投資部門別取引状況の週次CSV。"
    "海外投資家の日経225先物・mini・マイクロの売買代金差引。"
    "2026-09-24週のCSV金額は、同じ週の公式PDFの該当ページと一致した。"
    "出典URLを残す。売買条件には使わない。trading_adoption=false。"
)
PUBLICATION_RULE = (
    "毎週第4営業日（通常は木曜日、祝日等非営業日がある場合はその分後ろ倒し）"
    "午後3時30分に資料を掲載します。この文は掲載規則であり、個別ファイルのpublished_atではない。"
)
_CSV = re.compile(r"Tousi_DV_W_(20\d{6})_(20\d{6})\.csv$", re.I)


def _fetch(url: str) -> tuple[bytes, str | None]:
    request = Request(url, headers={"User-Agent": "TradeCockpit-JPX-PointInTime/1.0"})
    with urlopen(request, timeout=30) as response:
        body = response.read()
        if getattr(response, "status", 200) != 200 or not body:
            raise ValueError("MISSING")
        return body, response.headers.get("Last-Modified")


def discover_weekly_csvs(html: str) -> list[str]:
    links = re.findall(r"""href=["']([^"']+)["']""", html or "", flags=re.I)
    found = []
    for link in links:
        path = link.split("?", 1)[0]
        if _CSV.search(path):
            found.append(urljoin(PAGE, link))
    return list(dict.fromkeys(found))


def _column(header: list[str], prefix: str, *, exact: bool) -> int:
    hits = []
    for index, name in enumerate(header):
        token = name.strip().split(" ")[0]
        if exact and token == prefix:
            hits.append(index)
        elif not exact and token.startswith(prefix):
            hits.append(index)
    if len(hits) != 1:
        raise ValueError("MALFORMED")
    return hits[0]


def _yen(text: str) -> int:
    token = (text or "").replace(",", "").strip()
    if not re.fullmatch(r"-?\d+", token):
        raise ValueError("MALFORMED")
    return int(token)


def parse_investor_csv(blob: bytes) -> dict:
    try:
        text = blob.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("MALFORMED") from exc
    rows = list(csv.reader(text.splitlines()))
    if len(rows) < 2:
        raise ValueError("MALFORMED")
    header = rows[0]
    product_col = _column(header, "帳票種別", exact=False)
    investor_col = _column(header, "投資部門コード", exact=False)
    value_col = _column(header, "数量金額区分", exact=False)
    sell_col = _column(header, "売", exact=True)
    buy_col = _column(header, "買", exact=True)
    start_col = _column(header, "報告年月日（自）", exact=False)
    end_col = _column(header, "報告年月日（至）", exact=False)
    needed = max(product_col, investor_col, value_col, sell_col, buy_col, start_col, end_col)
    matched = {}
    for row in rows[1:]:
        if needed >= len(row):
            continue
        if row[investor_col].strip() != INVESTOR_CODE or row[value_col].strip() != "2":
            continue
        code = row[product_col].strip()
        if code not in PRODUCTS:
            continue
        if code in matched:
            raise ValueError("MALFORMED")
        matched[code] = {
            "sell_yen": _yen(row[sell_col]),
            "buy_yen": _yen(row[buy_col]),
            "period_start": row[start_col].strip(),
            "period_end": row[end_col].strip(),
        }
    if set(matched) != set(PRODUCTS):
        raise ValueError("MALFORMED")
    starts = {item["period_start"] for item in matched.values()}
    ends = {item["period_end"] for item in matched.values()}
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError("MALFORMED")
    start, end = starts.pop(), ends.pop()
    if not re.fullmatch(r"20\d{6}", start) or not re.fullmatch(r"20\d{6}", end):
        raise ValueError("MALFORMED")
    sell = sum(item["sell_yen"] for item in matched.values())
    buy = sum(item["buy_yen"] for item in matched.values())
    if min(sell, buy) < 0:
        raise ValueError("MALFORMED")
    session = f"{end[:4]}-{end[4:6]}-{end[6:]}"
    datetime.strptime(session, "%Y-%m-%d")
    return {
        "period_start": f"{start[:4]}-{start[4:6]}-{start[6:]}",
        "session_date": session,
        "investor_code": INVESTOR_CODE,
        "investor_label": "海外投資家",
        "products": PRODUCTS,
        "sell_yen": sell,
        "buy_yen": buy,
        "foreign_nikkei225_futures_net_yen": buy - sell,
        "unit": "yen",
        "basis": "trading_value_yen",
    }


def build_record(blob: bytes, source_url: str, fetched_at: datetime, last_modified: str | None = None) -> dict:
    parsed = parse_investor_csv(blob)
    name = _CSV.search(source_url.split("?", 1)[0])
    if name is None:
        raise ValueError("MALFORMED")
    expect_start = f"{name.group(1)[:4]}-{name.group(1)[4:6]}-{name.group(1)[6:]}"
    expect_end = f"{name.group(2)[:4]}-{name.group(2)[4:6]}-{name.group(2)[6:]}"
    if parsed["period_start"] != expect_start or parsed["session_date"] != expect_end:
        raise ValueError("MALFORMED")
    seen = fetched_at.astimezone(JST)
    published = jpx_calendar.verified_last_modified(last_modified, parsed["session_date"], seen)
    detail = jpx_calendar.weekly_freshness(parsed["session_date"], seen)
    net = parsed["foreign_nikkei225_futures_net_yen"]
    return {
        "id": "investor_futures_flow",
        "source": source_url,
        "source_page": PAGE,
        "first_seen_at": seen.isoformat(),
        "fetched_at": seen.isoformat(),
        "available_at": seen.isoformat(),
        "published_at": None if published is None else published.isoformat(),
        "published_at_basis": None if published is None else "http_last_modified",
        "publication_rule": PUBLICATION_RULE,
        "license_note": LICENSE_NOTE,
        "sha256": hashlib.sha256(blob).hexdigest(),
        "trading_adoption": False,
        "real_submit_allowed": False,
        "counts_as_live_sample": False,
        "promotion_candidate": False,
        "source_stage": "OFFICIAL_PUBLIC",
        **parsed,
        **detail,
        "foreign_nikkei225_futures_net_yen_for_research": net if detail["freshness"] == "FRESH" else None,
    }


def _existing_history() -> list[dict]:
    if not HISTORY.exists():
        return []
    rows = []
    for line in HISTORY.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not row.get("session_date") or not row.get("sha256"):
            raise ValueError("MALFORMED")
        raw = RAW / f"{row['sha256']}.csv"
        if not raw.exists() or hashlib.sha256(raw.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("MALFORMED")
        rows.append(row)
    return rows


def write_store(records: list[dict], blobs: dict[str, bytes]) -> dict:
    if not records:
        raise ValueError("MISSING")
    RAW.mkdir(parents=True, exist_ok=True)
    incoming = {}
    for record in records:
        blob = blobs.get(record["sha256"])
        if blob is None or hashlib.sha256(blob).hexdigest() != record["sha256"]:
            raise ValueError("MALFORMED")
        previous = incoming.get(record["session_date"])
        if previous is not None and previous["sha256"] != record["sha256"]:
            raise ValueError("MALFORMED")
        (RAW / f"{record['sha256']}.csv").write_bytes(blob)
        incoming[record["session_date"]] = record
    by_session = {row["session_date"]: row for row in _existing_history()}
    for session, record in incoming.items():
        previous = by_session.get(session)
        if previous and previous.get("sha256") == record["sha256"]:
            record = dict(record)
            seen = previous.get("first_seen_at") or previous["fetched_at"]
            verified_published = record.get("published_at")
            verified_basis = record.get("published_at_basis")
            record["first_seen_at"] = seen
            record["fetched_at"] = seen
            record["available_at"] = seen
            if previous.get("published_at"):
                record["published_at"] = previous["published_at"]
                record["published_at_basis"] = previous.get("published_at_basis")
            elif verified_published:
                record["published_at"] = verified_published
                record["published_at_basis"] = verified_basis
            detail = jpx_calendar.weekly_freshness(record["session_date"], datetime.fromisoformat(seen))
            record.update(detail)
            record["foreign_nikkei225_futures_net_yen_for_research"] = (
                record["foreign_nikkei225_futures_net_yen"] if detail["freshness"] == "FRESH" else None
            )
        by_session[session] = record
    ordered = [by_session[key] for key in sorted(by_session)]
    HISTORY.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in ordered), encoding="utf-8")
    latest = ordered[-1]
    LATEST.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return latest


def fetch_and_store(now: datetime | None = None) -> dict:
    fetched_at = now or datetime.now(JST)
    html, _header = _fetch(PAGE)
    urls = discover_weekly_csvs(html.decode("utf-8", "replace"))
    if not urls:
        raise ValueError("MISSING")
    records = []
    blobs = {}
    for url in urls:
        blob, last_modified = _fetch(url)
        record = build_record(blob, url, fetched_at, last_modified)
        blobs[record["sha256"]] = blob
        records.append(record)
    return write_store(records, blobs)


def load_latest(now: datetime | None = None) -> dict:
    closed = {
        "id": "investor_futures_flow",
        "fetch_status": "NOT_FETCHED",
        "freshness": "MISSING",
        "foreign_nikkei225_futures_net_yen": None,
        "foreign_nikkei225_futures_net_yen_for_research": None,
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
        record = json.loads(LATEST.read_text(encoding="utf-8"))
        required = ("source", "fetched_at", "available_at", "freshness", "license_note", "sha256", "session_date")
        if not isinstance(record, dict) or any(not record.get(key) for key in required):
            raise ValueError("MALFORMED")
        if record.get("trading_adoption") is not False or record.get("real_submit_allowed") is not False:
            raise ValueError("MALFORMED")
        if record.get("counts_as_live_sample") is not False or record.get("promotion_candidate") is not False:
            raise ValueError("MALFORMED")
        if record.get("source_stage") != "OFFICIAL_PUBLIC":
            raise ValueError("MALFORMED")
        net = record.get("foreign_nikkei225_futures_net_yen")
        if isinstance(net, bool) or not isinstance(net, int):
            raise ValueError("MALFORMED")
        if record.get("sell_yen") is None or record.get("buy_yen") is None:
            raise ValueError("MALFORMED")
        if record["buy_yen"] - record["sell_yen"] != net:
            raise ValueError("MALFORMED")
        raw = RAW / f"{record['sha256']}.csv"
        blob = raw.read_bytes() if raw.exists() else b""
        if hashlib.sha256(blob).hexdigest() != record["sha256"]:
            raise ValueError("MALFORMED")
        parsed = parse_investor_csv(blob)
        for key in ("session_date", "period_start", "sell_yen", "buy_yen", "foreign_nikkei225_futures_net_yen"):
            if record.get(key) != parsed[key]:
                raise ValueError("MALFORMED")
        seen = datetime.fromisoformat(record.get("first_seen_at") or record["fetched_at"])
        published = record.get("published_at")
        if published is not None:
            if record.get("published_at_basis") != "http_last_modified":
                raise ValueError("MALFORMED")
            stamp = datetime.fromisoformat(published)
            session = datetime.strptime(record["session_date"], "%Y-%m-%d").date()
            if stamp.tzinfo is None or stamp > seen or stamp.astimezone(JST).date() < session:
                raise ValueError("MALFORMED")
        clock = now or datetime.now(JST)
        at_fetch = jpx_calendar.weekly_freshness(record["session_date"], seen)
        current = jpx_calendar.weekly_freshness(record["session_date"], clock)
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
            record["foreign_nikkei225_futures_net_yen_for_research"] = net
            record["reason"] = "FRESH"
        else:
            record["foreign_nikkei225_futures_net_yen_for_research"] = None
            record["reason"] = current["freshness"] if current["freshness"] != "FRESH" else "STALE"
        return record
    except (OSError, json.JSONDecodeError, ValueError, TypeError, ImportError, UnicodeError):
        closed["fetch_status"] = "FAIL_CLOSED"
        closed["freshness"] = "MALFORMED"
        closed["reason"] = "MALFORMED"
        return closed
