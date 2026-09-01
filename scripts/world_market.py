#!/usr/bin/env python3
"""Collect market-regime data from nikkei225jp.com.

This feed is deliberately limited to indices, futures, FX, rates and risk
gauges.  It must never be used as an individual Japanese equity quote.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "world_market.json"
URL = "https://nikkei225jp.com/"
JST = timezone(timedelta(hours=9))

INSTRUMENTS = {
    "111": ("日経225", "japan"),
    "112": ("TOPIX", "japan"),
    "121": ("グロース250", "japan"),
    "751": ("DEX日経225", "realtime"),
    "511": ("ドル円", "realtime"),
    "151": ("日本10年金利", "realtime"),
    "211": ("NYダウ", "us_close"),
    "212": ("NASDAQ", "us_close"),
    "214": ("NASDAQ100", "us_close"),
    "213": ("S&P500", "us_close"),
    "611": ("SOX", "us_close"),
    "621": ("VIX", "us_close"),
    "811": ("米国10年金利", "realtime"),
}


class IdTextParser(HTMLParser):
    """Collect rendered text held by the small quote nodes (N/V/T/Z/P)."""

    def __init__(self) -> None:
        super().__init__()
        self.targets: dict[str, list[str]] = {}
        self.stack: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = dict(attrs).get("id")
        target = element_id if element_id and re.fullmatch(r"[NVTZP]\d{3}", element_id) else None
        self.stack.append(target or (self.stack[-1] if self.stack else None))
        if target:
            self.targets.setdefault(target, [])

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        if self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1]:
            self.targets.setdefault(self.stack[-1], []).append(data)

    def text(self, element_id: str) -> str | None:
        value = "".join(self.targets.get(element_id, [])).strip()
        return value or None


def number(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^0-9+\-.]", "", text.replace(",", ""))
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def freshness(stamp: str, kind: str, now: datetime) -> tuple[bool, str]:
    stamp = stamp.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", stamp):
        hh, mm = map(int, stamp.split(":"))
        observed = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        age = (now - observed).total_seconds() / 60
        return -2 <= age <= 90, observed.isoformat()
    if re.fullmatch(r"\d{2}/\d{2}", stamp):
        month, day = map(int, stamp.split("/"))
        observed = datetime(now.year, month, day, tzinfo=JST)
        if observed > now + timedelta(days=2):
            observed = observed.replace(year=now.year - 1)
        # US closes can legitimately be one calendar day behind in Japan.
        limit = 4 if kind == "us_close" else 1
        return 0 <= (now.date() - observed.date()).days <= limit, observed.date().isoformat()
    return False, stamp or "時刻なし"


def parse(html: str, now: datetime) -> dict:
    parser = IdTextParser()
    parser.feed(html)
    rows = {}
    for code, (label, kind) in INSTRUMENTS.items():
        source_name = parser.text(f"N{code}")
        stamp = parser.text(f"T{code}") or ""
        value = number(parser.text(f"V{code}"))
        fresh, observed_at = freshness(stamp, kind, now)
        verified = bool(source_name and value is not None and value > 0 and fresh)
        rows[code] = {
            "code": code,
            "name": label,
            "source_name": source_name,
            "value": value,
            "change": number(parser.text(f"Z{code}")),
            "change_pct": number(parser.text(f"P{code}")),
            "source_stamp": stamp or None,
            "observed_at": observed_at,
            "verified": verified,
            "status": "表示可" if verified else "未取得または時刻不整合・売買利用禁止",
        }
    verified_count = sum(bool(x["verified"]) for x in rows.values())
    return {
        "updated_at": now.isoformat(),
        "source": "世界の株価リアルタイムチャート",
        "source_url": URL,
        "usage": "市場環境専用。個別株価・個別チャートには使用禁止。",
        "verified_count": verified_count,
        "expected_count": len(rows),
        "feed_verified": verified_count >= 8,
        "rows": rows,
    }


def main() -> None:
    now = datetime.now(JST)
    result = {
        "updated_at": now.isoformat(),
        "source": "世界の株価リアルタイムチャート",
        "source_url": URL,
        "usage": "市場環境専用。個別株価・個別チャートには使用禁止。",
        "verified_count": 0,
        "expected_count": len(INSTRUMENTS),
        "feed_verified": False,
        "rows": {},
        "error": None,
    }
    try:
        request = Request(URL, headers={"User-Agent": "Mozilla/5.0 AI-Trade-Cockpit/1.0"})
        with urlopen(request, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
        result = parse(html, now)
        # Quotes are injected by the site's JavaScript.  If the initial HTML
        # is only a shell, render it once and parse the resulting DOM.
        if not result["feed_verified"]:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(URL, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_function("document.querySelector('#V111')?.innerText", timeout=15_000)
                page.wait_for_timeout(2_000)
                result = parse(page.content(), now)
                browser.close()
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if not result["feed_verified"]:
        raise SystemExit("world market feed failed freshness/coverage validation")


if __name__ == "__main__":
    main()
