"""100B read-only JPX 日々公表銘柄等信用取引残高 -> supply_sq evidence (v2).

Manual --fetch only. No model/API/Excel/broker/GitHub/scheduler integration.

Source: https://www.jpx.co.jp/markets/statistics-equities/margin/index.html
JPX publishes the file each business day "16:00を目安" for the previous
business day's application-based balances. It covers ONLY issues subject to
daily publication (regulated / 日々公表 / 注意喚起 etc.), NOT the daily margin
balance of every listed issue (that is J-Quants, a separate contract that is
not used here).

Time contract: the file states an as-of date and a publication date but no
release clock, so every record is DATE_ONLY_OBSERVED_AT_FETCH with
as_of = available_at = fetched_at = the verified fetch time. The dates are
kept in the summary. Nothing is inferred for an earlier time.

The fetched figures are kept in a private evidence file only (never GitHub).
Whether they may be sent to a paid model is an OWNER decision.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import io
import json
import re
import sys
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET
import zipfile

if __package__:
    from . import agent_sdk_public_feed_ingest as feed
else:
    import agent_sdk_public_feed_ingest as feed

HOST = "www.jpx.co.jp"
INDEX_URL = "https://www.jpx.co.jp/markets/statistics-equities/margin/index.html"
FILE_PATH = re.compile(r'href="(/markets/statistics-equities/margin/[A-Za-z0-9_-]+-att/(\d{8})_mtdaily\.xlsx)"')
SOURCE_NAME = "JPX 日々公表銘柄等信用取引残高 (Outstanding Margin Trading of Issues Subject to Daily Publication)"
TITLE = "日々公表銘柄等信用取引残高"
MAX_INDEX_BYTES = 524_288
MAX_XLSX_BYTES = 2_097_152
MAX_SHEET_XML_BYTES = 16_777_216
MAX_AGE_DAYS = 7
CODE = re.compile(r"^[0-9][0-9A-Z]{2}[0-9A-Z]0$")
ISIN = re.compile(r"^JP[0-9A-Z]{10}$")
REQUEST_CODE = re.compile(r"^[0-9][0-9A-Z]{3}$")
JST = timezone(timedelta(hours=9))
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class MarginBlocked(ValueError):
    """Fail closed; never fabricate a balance."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _get(url: str, limit: int) -> bytes:
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != HOST or parts.port is not None
            or parts.username or parts.password or parts.query or parts.fragment
            or not parts.path.startswith("/markets/statistics-equities/margin/")):
        raise MarginBlocked("JPX_URL_NOT_ALLOWLISTED")
    request = Request(url, headers={"User-Agent": "100B-Cockpit-Public-Research/0.1 (manual; no trading)"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            if response.status != 200:
                raise MarginBlocked("JPX_HTTP_NOT_OK")
            raw = response.read(limit + 1)
    except MarginBlocked:
        raise
    except Exception as exc:
        raise MarginBlocked("JPX_FETCH_UNAVAILABLE") from exc
    if len(raw) > limit:
        raise MarginBlocked("JPX_SIZE_LIMIT")
    return raw


def latest_file_url(index_html: bytes) -> str:
    """Pick the newest *_mtdaily.xlsx linked from the official index page."""
    text = index_html.decode("utf-8", errors="replace")
    found = sorted({(m.group(2), m.group(1)) for m in FILE_PATH.finditer(text)})
    if not found:
        raise MarginBlocked("JPX_MARGIN_FILE_LINK_NOT_FOUND")
    return urljoin(INDEX_URL, found[-1][1])


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx_rows(raw: bytes) -> list[list[str]]:
    """First worksheet as rows of strings (standard library only)."""
    if len(raw) > MAX_XLSX_BYTES:
        raise MarginBlocked("JPX_SIZE_LIMIT")
    try:
        book = zipfile.ZipFile(io.BytesIO(raw))
        names = set(book.namelist())

        def xml(name):
            info = book.getinfo(name)
            if info.file_size > MAX_SHEET_XML_BYTES:
                raise MarginBlocked("JPX_XLSX_PART_TOO_LARGE")
            data = book.read(name)
            if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                raise MarginBlocked("JPX_XLSX_DTD_FORBIDDEN")
            return ET.fromstring(data)

        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in xml("xl/sharedStrings.xml").findall("m:si", NS):
                # direct text and rich-text runs only; phonetic guides (rPh) are not content
                parts = [si.find("m:t", NS)] + [run.find("m:t", NS) for run in si.findall("m:r", NS)]
                shared.append("".join(t.text or "" for t in parts if t is not None))
        workbook = xml("xl/workbook.xml")
        first = workbook.find("m:sheets/m:sheet", NS)
        rid = first.get("{%s}id" % REL_NS)
        target = None
        for rel in xml("xl/_rels/workbook.xml.rels"):
            if rel.get("Id") == rid:
                target = rel.get("Target")
        if not target:
            raise MarginBlocked("JPX_XLSX_SHEET_MISSING")
        target = target.lstrip("/")
        path = target if target.startswith("xl/") else "xl/" + target
        sheet = xml(path)
    except MarginBlocked:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError, AttributeError, ValueError) as exc:
        raise MarginBlocked("JPX_XLSX_INVALID") from exc
    rows = []
    for row in sheet.iter("{%s}row" % NS["m"]):
        cells = {}
        for c in row.findall("m:c", NS):
            kind, v = c.get("t"), c.find("m:v", NS)
            if kind == "s" and v is not None:
                value = shared[int(v.text)]
            elif kind == "inlineStr":
                value = "".join(t.text or "" for t in c.iter("{%s}t" % NS["m"]))
            else:
                value = v.text if v is not None and v.text is not None else ""
            cells[_col(c.get("r"))] = value.strip()
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows


def _day(raw: str) -> date:
    m = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", raw)
    if not m:
        raise MarginBlocked("JPX_DATE_INVALID")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _num(raw: str) -> int | float:
    text = raw.replace(",", "").replace("▲", "-").strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?([eE][+-]?\d+)?", text):
        raise MarginBlocked("JPX_NUMBER_INVALID")
    value = float(text)
    return int(value) if value.is_integer() else value


def parse_margin(rows: list[list[str]], *, observed_at: datetime) -> dict:
    """Dates and per-issue balances. Blocks on unknown layout or dates."""
    if observed_at.utcoffset() is None:
        raise MarginBlocked("JPX_CLOCK_UNVERIFIED")
    if not any(TITLE in cell for row in rows for cell in row):
        raise MarginBlocked("JPX_MARGIN_TITLE_NOT_FOUND")
    as_of = published = None
    for row in rows:
        if "申込み現在" in row:
            i = row.index("申込み現在")
            before = [c for c in row[:i] if c]
            after = [c for c in row[i + 1:] if c]
            if not before or not after:
                raise MarginBlocked("JPX_MARGIN_DATES_NOT_FOUND")
            as_of, published = _day(before[-1]), _day(after[0])
            break
    if as_of is None:
        raise MarginBlocked("JPX_MARGIN_DATES_NOT_FOUND")
    today = observed_at.astimezone(JST).date()
    if published < as_of or published > today or (today - published).days > MAX_AGE_DAYS:
        raise MarginBlocked("JPX_MARGIN_FILE_STALE_OR_FUTURE")
    issues = {}
    for row in rows:
        for i, cell in enumerate(row):
            if ISIN.fullmatch(cell) and i >= 4 and CODE.fullmatch(row[i - 1]):
                nums = row[i + 1:i + 8]
                try:
                    # 上場比 (positions 2 and 5) is "*" for ETFs/ETNs: not calculated, kept as None.
                    values = [None if k in (2, 5) and x == "*" else _num(x) for k, x in enumerate(nums)]
                except MarginBlocked:
                    break  # a malformed row is skipped, never guessed
                if len(values) != 7:
                    break
                code = row[i - 1][:4]
                issues[code] = {
                    "code": code, "name": row[i - 4], "market": row[i - 3], "loan_type": row[i - 2],
                    "sales": int(values[0]), "sales_change": int(values[1]), "purchases": int(values[3]),
                    "purchases_change": int(values[4]), "sale_purchase_ratio": float(values[6]),
                }
                break
    if not issues:
        raise MarginBlocked("JPX_MARGIN_NO_ISSUE_ROWS")
    return {"as_of_date": as_of.isoformat(), "published_date": published.isoformat(), "issues": issues}


def build_sources(parsed: dict, codes: list[str], file_url: str, *, observed_at: datetime) -> list[dict]:
    now = observed_at.astimezone(timezone.utc).isoformat()
    out = []
    for code in codes:
        item = parsed["issues"].get(code)
        if item is None:
            continue  # not a daily-publication issue today: no record, no guess
        summary = (
            f"JPX日々公表銘柄等信用取引残高 {parsed['as_of_date']}申込み現在 ({parsed['published_date']}公表, 16:00目安): "
            f"{item['name']}({code}) 売残{item['sales']:,}株(前日比{item['sales_change']:+,}) "
            f"買残{item['purchases']:,}株(前日比{item['purchases_change']:+,}) 取組比率{item['sale_purchase_ratio']}%. "
            "日々公表対象銘柄のみ・全銘柄の日次信用残ではない。DATE_ONLY_OBSERVED_AT_FETCH。売買シグナルではない"
        )[:400]
        out.append({
            "source_id": "jpx_margin_" + code + "_" + parsed["published_date"].replace("-", ""),
            "role": "supply_sq",
            "source_url": file_url,
            "source_name": SOURCE_NAME,
            "source_type": "OFFICIAL_STATISTICS_FILE",
            "as_of": now, "available_at": now, "fetched_at": now,
            "data_status": "DATE_ONLY_OBSERVED_AT_FETCH",
            "summary": summary,
        })
    return out


def parse_codes(raw: str) -> list[str]:
    codes = [c.strip().upper() for c in raw.split(",") if c.strip()]
    if not codes or len(codes) > 30 or any(not REQUEST_CODE.fullmatch(c) for c in codes):
        raise MarginBlocked("JPX_CODES_INVALID")
    return sorted(set(codes))


def fetch_sources(codes: list[str], *, observed_at: datetime) -> tuple[list[dict], dict]:
    url = latest_file_url(_get(INDEX_URL, MAX_INDEX_BYTES))
    parsed = parse_margin(read_xlsx_rows(_get(url, MAX_XLSX_BYTES)), observed_at=observed_at)
    rows = build_sources(parsed, codes, url, observed_at=observed_at)
    meta = {"file": url.rsplit("/", 1)[-1], "as_of_date": parsed["as_of_date"],
            "published_date": parsed["published_date"], "matched_codes": [r["source_id"].split("_")[2] for r in rows],
            "issue_count_in_file": len(parsed["issues"])}
    return rows, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Manual JPX daily-publication margin evidence builder")
    ap.add_argument("--fetch", action="store_true", required=True)
    ap.add_argument("--codes", required=True, help="Comma separated 4-character codes, e.g. 285A,8035")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args(argv)
    try:
        from pathlib import Path
        rows, meta = fetch_sources(parse_codes(args.codes), observed_at=datetime.now(timezone.utc))
        if not rows:
            raise MarginBlocked("JPX_MARGIN_NO_REQUESTED_ISSUE_PUBLISHED")
        if not feed.RUN_ID.fullmatch(args.run_id):
            raise MarginBlocked("RUN_ID_INVALID")
        feed.write_once(Path(args.output), {"schema_version": feed.SCHEMA, "run_id": args.run_id, "sources": rows})
        print(json.dumps({"status": "PUBLIC_STATISTICS_SNAPSHOT_WRITTEN_RESEARCH_ONLY", "sources": len(rows),
                          **meta, "model_calls": 0, "real_submit_allowed": False}, ensure_ascii=False, sort_keys=True))
        return 0
    except (MarginBlocked, feed.EvidenceBlocked, OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, (MarginBlocked, feed.EvidenceBlocked)) else "JPX_IO_BLOCKED"
        print(json.dumps({"status": "BLOCKED", "reason": reason, "model_calls": 0, "real_submit_allowed": False}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
