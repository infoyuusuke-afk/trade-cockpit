"""100B read-only JPX 銘柄別信用取引残高 (all issues, every business day) -> supply_sq evidence.

OWNER 2026-10-22 「JPXの信用残は『銘柄別信用取引残高』（毎営業日16時、全銘柄）から取って。
日々公表銘柄の一覧ではなく、こっちを使って」.

Source: https://www.jpx.co.jp/markets/statistics-equities/margin/01.html
JPX posts YYYYMMDD_mtall.pdf "日々16:00を目安" for the previous business day's
application-based balances of every margin issue (about 4,200). Only a PDF is
published. Each issue block reads: code (e.g. 285A0), "JP... 株数 Shs.", then
fourteen figures: sales, change, ratio to listed, purchases, change, ratio,
negotiable sales, change, standardized sales, change, negotiable purchases,
change, standardized purchases, change. A block is kept only when its totals
equal negotiable + standardized for both balances and both changes, so a
misread block is dropped, never guessed.

Time contract as the daily-publication adapter: the file states dates but no
release clock, so every record is DATE_ONLY_OBSERVED_AT_FETCH at the verified
fetch time. Manual --fetch only. No model/API/Excel/broker/scheduler. Whether
the figures may be sent to a paid model is an OWNER decision (recorded
2026-10-22 「JPX渡してOK」, still enforced per run by the pilot).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re

if __package__:
    from . import agent_sdk_jpx_margin_ingest as daily
else:
    import agent_sdk_jpx_margin_ingest as daily

MarginBlocked = daily.MarginBlocked
PAGE_URL = "https://www.jpx.co.jp/markets/statistics-equities/margin/01.html"
FILE_PATH = re.compile(r'href="(/markets/statistics-equities/margin/[A-Za-z0-9_-]+-att/(\d{8})_mtall\.pdf)"')
SOURCE_NAME = "JPX 銘柄別信用取引残高 (Outstanding Margin Trading by Issue, all issues)"
MAX_PDF_BYTES = 8_388_608
MAX_AGE_DAYS = 7
MAX_CODES = 150
ISSUES_PER_SOURCE = 7
CODE_LINE = re.compile(r"^([0-9][0-9A-Z]{2}[0-9A-Z])0$")
ISIN_LINE = re.compile(r"^JP[0-9A-Z]{10} 株数 Shs\.\s*$")
FIGURE = re.compile(r"^(?:▲ )?[\d,]+$|^-$|^\*$|^[\d.]+%$")
AS_OF = re.compile(r"(\d{4})/(\d{2})/(\d{2}) 申込み現在")


def latest_file_url(html: bytes) -> str:
    found = sorted({(m.group(2), m.group(1)) for m in FILE_PATH.finditer(html.decode("utf-8", "replace"))})
    if not found:
        raise MarginBlocked("JPX_MTALL_FILE_LINK_NOT_FOUND")
    return "https://" + daily.HOST + found[-1][1]


def _value(text: str) -> int:
    raw = text.replace(",", "")
    return -int(raw[2:]) if raw.startswith("▲ ") else int(raw)


def parse_lines(lines: list[str], *, observed_at: datetime) -> dict:
    as_of = None
    for line in lines[:400]:
        m = AS_OF.search(line)
        if m:
            as_of = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            break
    if as_of is None:
        raise MarginBlocked("JPX_MTALL_AS_OF_NOT_FOUND")
    local = observed_at.astimezone(daily.JST).date()
    if not timedelta(0) <= local - as_of <= timedelta(days=MAX_AGE_DAYS):
        raise MarginBlocked("JPX_MTALL_FILE_STALE_OR_FUTURE")
    issues, dropped, i, n = {}, 0, 0, len(lines)
    while i < n - 1:
        m = CODE_LINE.match(lines[i])
        if not (m and ISIN_LINE.match(lines[i + 1])):
            i += 1
            continue
        figures, j = [], i + 2
        while j < n and len(figures) < 14:
            if FIGURE.match(lines[j]):
                figures.append(lines[j])
            j += 1
        i = j
        try:
            s, sc, _, b, bc, _, ns, nsc, ss, ssc, nb, nbc, sb, sbc = [_value(x) if x not in ("-", "*") and not x.endswith("%")
                                                                     else None for x in figures]
            if None in (s, sc, b, bc, ns, nsc, ss, ssc, nb, nbc, sb, sbc) or s != ns + ss or b != nb + sb \
                    or sc != nsc + ssc or bc != nbc + sbc:
                raise ValueError
        except ValueError:
            dropped += 1  # a block that does not add up is dropped, never guessed
            continue
        issues[m.group(1)] = {"code": m.group(1), "sales": s, "sales_change": sc, "purchases": b,
                              "purchases_change": bc, "standardized_sales": ss, "standardized_purchases": sb}
    if not issues:
        raise MarginBlocked("JPX_MTALL_NO_ISSUE_ROWS")
    return {"as_of_date": as_of.isoformat(), "issues": issues, "dropped_blocks": dropped}


def read_pdf_lines(raw: bytes) -> list[str]:
    try:
        import pymupdf
    except ImportError as exc:
        raise MarginBlocked("PDF_READER_MISSING") from exc
    try:
        doc = pymupdf.open(stream=raw, filetype="pdf")
        return [line.strip() for page in doc for line in page.get_text().split("\n")]
    except Exception as exc:
        raise MarginBlocked("JPX_MTALL_PDF_UNREADABLE") from exc


def parse_codes(raw: str) -> list[str]:
    codes = [c.strip().upper() for c in raw.split(",") if c.strip()]
    if not codes or len(codes) > MAX_CODES or any(not daily.REQUEST_CODE.fullmatch(c) for c in codes):
        raise MarginBlocked("JPX_CODES_INVALID")
    return list(dict.fromkeys(codes))  # keep the caller's priority order


def _short(n: int) -> str:
    return f"{n / 10000:,.1f}万" if abs(n) >= 10000 else f"{n:,}"


def _item(x: dict) -> str:
    ratio = f"{x['purchases'] / x['sales']:.2f}" if x["sales"] else "-"
    return (f"{x['code']} 売{_short(x['sales'])}({_short(x['sales_change'])}) "
            f"買{_short(x['purchases'])}({_short(x['purchases_change'])}) 倍{ratio}")


def build_sources(parsed: dict, codes: list[str], file_url: str, *, observed_at: datetime) -> list[dict]:
    """Compact records of at most ISSUES_PER_SOURCE issues and 400 characters each, in the
    caller's order. 倍 = purchases / sales. Issues not in the file get no record."""
    now = observed_at.astimezone(timezone.utc).isoformat()
    head = f"JPX銘柄別信用取引残高 {parsed['as_of_date']}申込み現在(全銘柄・16:00目安公表): "
    tail = ". 単位株・前日比は括弧内。売買シグナルではない"
    groups, current = [], []
    for code in codes:
        x = parsed["issues"].get(code)
        if x is None:
            continue
        if current and (len(current) >= ISSUES_PER_SOURCE or
                        len(head + "; ".join(current + [_item(x)]) + tail) > 400):
            groups.append(current)
            current = []
        current.append(_item(x))
    if current:
        groups.append(current)
    return [{
        "source_id": "jpx_mtall_" + parsed["as_of_date"].replace("-", "") + "_" + str(k + 1),
        "role": "supply_sq",
        "source_url": file_url,
        "source_name": SOURCE_NAME,
        "source_type": "OFFICIAL_STATISTICS_FILE",
        "as_of": now, "available_at": now, "fetched_at": now,
        "data_status": "DATE_ONLY_OBSERVED_AT_FETCH",
        "summary": head + "; ".join(g) + tail,
    } for k, g in enumerate(groups)]


def fetch_sources(codes: list[str], *, observed_at: datetime) -> tuple[list[dict], dict]:
    url = latest_file_url(daily._get(PAGE_URL, daily.MAX_INDEX_BYTES))
    parsed = parse_lines(read_pdf_lines(daily._get(url, MAX_PDF_BYTES)), observed_at=observed_at)
    rows = build_sources(parsed, codes, url, observed_at=observed_at)
    meta = {"file": url.rsplit("/", 1)[-1], "as_of_date": parsed["as_of_date"],
            "issue_count_in_file": len(parsed["issues"]), "dropped_blocks": parsed["dropped_blocks"],
            "matched_codes": [c for c in codes if c in parsed["issues"]]}
    return rows, meta
