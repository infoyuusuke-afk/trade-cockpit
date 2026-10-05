"""JPX daily short-sale aggregate. Research reference only.

The PDF is a public Tokyo Stock Exchange total. It is not a broker tariff,
not a holding, and not a live entry input. trading_adoption stays false.
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
STORE = ROOT / "data" / "research_lane" / "short_sale_ratio"
RAW = STORE / "raw"
LATEST = STORE / "latest.json"
HISTORY = STORE / "history.jsonl"
PAGE = "https://www.jpx.co.jp/markets/statistics-equities/short-selling/"
JST = timezone(timedelta(hours=9))
LICENSE_NOTE = (
    "JPX/東証が公開する立会市場の空売り売買代金の合計。個別の保有や注文ではない。"
    "出典URLを残す。売買条件には使わない。trading_adoption=false。"
)
_ROW = re.compile(
    r"(20\d{2})年(\d{1,2})月(\d{1,2})日\s+"
    r"([\d,]+)\s+([\d.]+)%\s+"
    r"([\d,]+)\s+([\d.]+)%\s+"
    r"([\d,]+)\s+([\d.]+)%\s+"
    r"([\d,]+)"
)


def _int(text: str) -> int:
    return int(text.replace(",", ""))


def parse_short_sale_text(text: str) -> dict:
    """Read one official total row. A broken total is rejected."""
    matched = _ROW.search(text or "")
    if not matched:
        raise ValueError("MALFORMED")
    year, month, day, a_text, a_pct, b_text, b_pct, c_text, c_pct, d_text = matched.groups()
    actual = _int(a_text)
    regulated = _int(b_text)
    unregulated = _int(c_text)
    total = _int(d_text)
    if min(actual, regulated, unregulated, total) < 0 or total <= 0:
        raise ValueError("MALFORMED")
    if actual + regulated + unregulated != total:
        raise ValueError("MALFORMED")
    published = (float(a_pct), float(b_pct), float(c_pct))
    values = (actual, regulated, unregulated)
    for value, ratio in zip(values, published):
        if abs((value / total) * 100 - ratio) > 0.15:
            raise ValueError("MALFORMED")
    session = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    datetime.strptime(session, "%Y-%m-%d")
    short_ratio = (regulated + unregulated) / total
    return {
        "session_date": session,
        "actual_order_million_yen": actual,
        "short_regulated_million_yen": regulated,
        "short_unregulated_million_yen": unregulated,
        "total_million_yen": total,
        "actual_order_pct": published[0],
        "short_regulated_pct": published[1],
        "short_unregulated_pct": published[2],
        "short_ratio": round(short_ratio, 6),
        "unit": "million_yen",
    }


def freshness(session_date: str, fetched_at: datetime) -> str:
    return jpx_calendar.daily_freshness(session_date, fetched_at)["freshness"]


def _pdf_text(blob: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(blob))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _fetch(url: str) -> tuple[bytes, str | None]:
    request = Request(url, headers={"User-Agent": "TradeCockpit-JPX-PointInTime/1.0"})
    with urlopen(request, timeout=30) as response:
        body = response.read()
        if getattr(response, "status", 200) != 200 or not body:
            raise ValueError("MISSING")
        return body, response.headers.get("Last-Modified")


def discover_market_pdfs(html: str) -> list[str]:
    links = re.findall(r"""href=["']([^"']+)["']""", html or "", flags=re.I)
    found = []
    for link in links:
        path = link.split("?", 1)[0].lower()
        if path.endswith("-m.pdf"):
            found.append(urljoin(PAGE, link))
    return list(dict.fromkeys(found))


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
    if not blob.startswith(b"%PDF"):
        raise ValueError("MALFORMED")
    parsed = parse_short_sale_text(_pdf_text(blob))
    digest = hashlib.sha256(blob).hexdigest()
    clock = _clock_fields(parsed["session_date"], fetched_at, last_modified)
    return {
        "id": "short_sale_ratio",
        "source": source_url,
        "source_page": PAGE,
        "license_note": LICENSE_NOTE,
        "sha256": digest,
        "trading_adoption": False,
        "real_submit_allowed": False,
        "counts_as_live_sample": False,
        "promotion_candidate": False,
        "source_stage": "OFFICIAL_PUBLIC",
        **parsed,
        **clock,
        "short_ratio_for_research": parsed["short_ratio"] if clock["freshness"] == "FRESH" else None,
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
        raw = RAW / f"{row['sha256']}.pdf"
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
        (RAW / f"{record['sha256']}.pdf").write_bytes(blob)
        incoming[record["session_date"]] = record
    by_session = {row["session_date"]: row for row in _existing_history()}
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
            record["short_ratio_for_research"] = (
                record["short_ratio"] if detail["freshness"] == "FRESH" else None
            )
        by_session[session] = record
    ordered = [by_session[key] for key in sorted(by_session)]
    HISTORY.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in ordered),
        encoding="utf-8",
    )
    latest = ordered[-1]
    LATEST.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return latest


def fetch_and_store(now: datetime | None = None) -> dict:
    fetched_at = now or datetime.now(JST)
    html, _header = _fetch(PAGE)
    urls = discover_market_pdfs(html.decode("utf-8", "replace"))
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
    """Return the stored row, or a closed empty row. Never invent a ratio."""
    closed = {
        "id": "short_sale_ratio",
        "fetch_status": "NOT_FETCHED",
        "freshness": "MISSING",
        "short_ratio": None,
        "short_ratio_for_research": None,
        "trading_adoption": False,
        "real_submit_allowed": False,
        "counts_as_live_sample": False,
        "promotion_candidate": False,
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
        ratio = record.get("short_ratio")
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 0 <= ratio <= 1:
            raise ValueError("MALFORMED")
        raw = RAW / f"{record['sha256']}.pdf"
        blob = raw.read_bytes() if raw.exists() else b""
        if hashlib.sha256(blob).hexdigest() != record["sha256"]:
            raise ValueError("MALFORMED")
        parsed = parse_short_sale_text(_pdf_text(blob))
        for key in (
            "session_date",
            "actual_order_million_yen",
            "short_regulated_million_yen",
            "short_unregulated_million_yen",
            "total_million_yen",
            "short_ratio",
        ):
            if record.get(key) != parsed[key]:
                raise ValueError("MALFORMED")
        seen_text = record.get("first_seen_at") or record.get("fetched_at")
        seen = datetime.fromisoformat(seen_text)
        published = record.get("published_at")
        if published is not None:
            if record.get("published_at_basis") != "http_last_modified":
                raise ValueError("MALFORMED")
            stamp = datetime.fromisoformat(published)
            session = datetime.strptime(record["session_date"], "%Y-%m-%d").date()
            if stamp.tzinfo is None or stamp > seen or stamp.astimezone(JST).date() < session:
                raise ValueError("MALFORMED")
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
            record["short_ratio_for_research"] = record["short_ratio"]
            record["reason"] = "FRESH"
        else:
            record["short_ratio_for_research"] = None
            record["reason"] = current["freshness"] if current["freshness"] != "FRESH" else "STALE"
        return record
    except (OSError, json.JSONDecodeError, ValueError, TypeError, ImportError):
        closed["fetch_status"] = "FAIL_CLOSED"
        closed["freshness"] = "MALFORMED"
        closed["reason"] = "MALFORMED"
        return closed


# Sum of five 0-5 scores. This is an ordinal research priority, not yen expectancy.
# contribution, license clarity, history fetchability, implementation speed, available_at clarity.
LANE_PRIORITY = (
    {"id": "short_sale_ratio", "rank": 1, "contribution": 5, "license": 5, "history": 5, "speed": 5, "available_at": 3, "score": 23, "fetch_this_turn": True, "why": "JPXの日次合計。出典付きの公開統計。履歴PDFがある。PDFに時刻は無いのでavailable_atは初回観測時刻。"},
    {"id": "investor_futures_flow", "rank": 2, "contribution": 4, "license": 5, "history": 5, "speed": 4, "available_at": 4, "score": 22, "fetch_this_turn": True, "why": "JPX先物の投資部門別。週次CSVを取得する。公表時刻はLast-Modifiedが検証できたときだけ入れる。"},
    {"id": "arbitrage_balance", "rank": 3, "contribution": 5, "license": 4, "history": 3, "speed": 2, "available_at": 3, "score": 17, "fetch_this_turn": False, "why": "プログラム売買ページは確認した。PDFは参加者別で、合計だけを切る処理が未完了。参加者名は保存しない。"},
    {"id": "earnings_schedule", "rank": 4, "contribution": 3, "license": 4, "history": 4, "speed": 3, "available_at": 3, "score": 17, "fetch_this_turn": False, "why": "裁定残と同点。日程であり需給の数値ではない。既存の日程読取とは別に、今回の取得対象にはしない。"},
    {"id": "macro_release", "rank": 5, "contribution": 3, "license": 3, "history": 3, "speed": 2, "available_at": 4, "score": 15, "fetch_this_turn": False, "why": "予定時刻だけがある。結果の数値系列は未接続。"},
    {"id": "catalyst", "rank": 6, "contribution": 3, "license": 3, "history": 2, "speed": 1, "available_at": 4, "score": 13, "fetch_this_turn": False, "why": "TDnet見出しは開示時刻がある。この環境からの取得は403で、本文はコピーしない。"},
    {"id": "futures_options_positioning", "rank": 7, "contribution": 4, "license": 2, "history": 2, "speed": 1, "available_at": 3, "score": 12, "fetch_this_turn": False, "why": "IVとPCRは未契約。建玉の公式日次だけを分ける処理はまだ無い。"},
    {"id": "nt_ratio", "rank": 8, "contribution": 4, "license": 1, "history": 1, "speed": 1, "available_at": 3, "score": 10, "fetch_this_turn": False, "why": "日経平均の再配布条件が無い。TOPIXだけではNT倍率にならない。"},
    {"id": "korea_equity", "rank": 9, "contribution": 3, "license": 1, "history": 1, "speed": 1, "available_at": 3, "score": 9, "fetch_this_turn": False, "why": "KRXのページは公開されている。系列の利用条件は未確認なので値は取らない。"},
    {"id": "crude", "rank": 10, "contribution": 2, "license": 1, "history": 1, "speed": 1, "available_at": 3, "score": 8, "fetch_this_turn": False, "why": "CMEの候補ページは未契約。この環境からは値を取っていない。"},
    {"id": "gold", "rank": 11, "contribution": 2, "license": 1, "history": 1, "speed": 1, "available_at": 3, "score": 8, "fetch_this_turn": False, "why": "COMEX金の候補ページは未契約。この環境からは値を取っていない。"},
    {"id": "midterm_plan", "rank": 12, "contribution": 2, "license": 2, "history": 0, "speed": 0, "available_at": 2, "score": 6, "fetch_this_turn": False, "why": "各社IRの本文はコピーしない。構造化系列は無い。"},
    {"id": "shikiho_fundamentals", "rank": 13, "contribution": 3, "license": 0, "history": 0, "speed": 0, "available_at": 2, "score": 5, "fetch_this_turn": False, "why": "四季報は転載しない。契約が無いので取得しない。"},
    {"id": "official_speech", "rank": 14, "contribution": 2, "license": 1, "history": 0, "speed": 0, "available_at": 1, "score": 4, "fetch_this_turn": False, "why": "構造化された要人発言フィードは未確認。"},
    {"id": "copper", "rank": 15, "contribution": 2, "license": 1, "history": 0, "speed": 0, "available_at": 1, "score": 4, "fetch_this_turn": False, "why": "銅先物の公式系列はこのリポジトリに無い。"},
    {"id": "silver", "rank": 16, "contribution": 2, "license": 1, "history": 0, "speed": 0, "available_at": 1, "score": 4, "fetch_this_turn": False, "why": "銀先物の取得コードは無い。"},
    {"id": "credit_evaluation_loss", "rank": 17, "contribution": 3, "license": 0, "history": 0, "speed": 0, "available_at": 0, "score": 3, "fetch_this_turn": False, "why": "取引所の単一系列は未確認。ソースが特定できるまで取得しない。"},
)
FETCH_RANK = tuple(row for row in LANE_PRIORITY if row["rank"] <= 3)
NOT_FETCHED_BECAUSE = {
    "nt_ratio": "日経平均の再配布条件が無い。TOPIXだけではNT倍率にならない。",
    "futures_options_positioning": "IVとPCRは未契約。建玉の公式日次ファイルは別系列で、今回は切っていない。",
    "jpx_nikkei_mid_small": "JPX日経中小型は日経の指数条件が未確認。Registryの17項目には無く、取得しない。",
    "dex": "DEXはC-189の研究ゲート配下。ライセンスを新たに確認するまで取得しない。",
    "tradingview_wide": "TradingViewの非公式APIは利用条件が未確認。売買候補には使わない。",
}
