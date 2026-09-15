"""scripts/market_ranking_watch.py

外部ランキング発掘（C-041で確認した代替案。docs/AI_SHARED_SHEET.md C-041参照）。

MS2 RSSには市場全体のランキング（値上がり率・出来高急増・売買代金）を取得する
関数が存在しないと公式ヘルプで確認済み。固定100銘柄ウォッチリスト
（ms2_live/watchlist_100.json）に入っていない銘柄の急騰・出来高急増は、
このリポジトリの既存パイプラインでは検知できていなかった。

Yahoo!ファイナンスの公開ランキングページ（値上がり率・出来高急増率・売買代金上位）
を取得し、固定ウォッチリストに無い銘柄を一覧化する。

## 正直な制約
- Yahoo!ファイナンスの遅延/日次データであり、MS2 RSSのリアルタイムデータではない。
  そのため $buy/$short 判定・音声通知には一切使用しない（表示専用・参考情報）。
- ウォッチリストへの自動追加は行わない。人が見て判断する一覧を出すだけ。
- ページ構造が変わって1件もパースできなかった場合は空リストを返す（推定で埋めない）。
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from lxml import html as LH

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
WATCHLIST_PATH = ROOT / "ms2_live" / "watchlist_100.json"
OUT_PATH = ROOT / "market_ranking_watch.json"

RANKINGS = [
    ("up", "値上がり率", "https://finance.yahoo.co.jp/stocks/ranking/up?market=tokyo1"),
    ("volume_increase", "出来高急増率", "https://finance.yahoo.co.jp/stocks/ranking/volumeIncrease?market=all"),
    ("trading_value", "売買代金上位", "https://finance.yahoo.co.jp/stocks/ranking/tradingValueHigh?market=all"),
]
TOP_N = 20


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 trade-cockpit-public-ranking/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _text(el) -> Optional[str]:
    if el is None:
        return None
    t = el.text_content().strip()
    return t or None


def parse_ranking_html(html_bytes_or_str) -> list[dict]:
    """Yahoo!ファイナンスのランキングテーブルを純粋にパースする（fetchと分離、テスト対象）。
    2026-09-16時点の実機DOM調査に基づく（tr.RankingTable__row, td順=名称/取引値/前日比/出来高）。
    """
    tree = LH.fromstring(html_bytes_or_str)
    rows = tree.xpath('//tr[contains(@class,"RankingTable__row")]')
    results = []
    for row in rows:
        rank_el = row.xpath('.//th[contains(@class,"RankingTable__rank")]')
        tds = row.xpath("./td")
        if not rank_el or len(tds) < 4:
            continue
        rank_text = _text(rank_el[0])
        name_link = tds[0].xpath('.//a[contains(@href,"/quote/")]')
        if not rank_text or not rank_text.isdigit() or not name_link:
            continue
        name = _text(name_link[0])
        href = name_link[0].get("href", "")
        slug = href.rstrip("/").split("/")[-1]
        code = slug[:-2] if slug.endswith(".T") else None
        supplements = tds[0].xpath('.//li[contains(@class,"RankingTable__supplement")]')
        market = _text(supplements[1]) if len(supplements) > 1 else None
        price_values = tds[1].xpath('.//span[contains(@class,"StyledNumber__value")]')
        price = _text(price_values[0]) if price_values else None
        change_values = tds[2].xpath('.//span[contains(@class,"StyledNumber__value")]')
        change_yen = _text(change_values[0]) if len(change_values) > 0 else None
        change_pct = _text(change_values[1]) if len(change_values) > 1 else None
        volume_values = tds[3].xpath('.//span[contains(@class,"StyledNumber__value")]')
        volume = _text(volume_values[0]) if volume_values else None
        if not (name and code):
            continue
        results.append({
            "rank": int(rank_text),
            "name": name,
            "code": code,
            "market": market,
            "price": price,
            "change_yen": change_yen,
            "change_pct": change_pct,
            "volume": volume,
        })
    return results


def load_watched_codes(path: Path = WATCHLIST_PATH) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    codes = set()
    for meta in (data.get("stocks") or {}).values():
        ticker = str(meta.get("ticker") or "")
        code = ticker.split(".")[0]
        if code:
            codes.add(code)
    return codes


def annotate_watched(items: list[dict], watched_codes: set[str]) -> list[dict]:
    """純粋関数：各行に already_watched を付与する（テスト対象）。"""
    return [{**item, "already_watched": item["code"] in watched_codes} for item in items]


def fetch_ranking(url: str) -> list[dict]:
    """1ランキングページを取得しパースする。通常のHTML取得で0件だった場合のみ、
    JS描画の可能性を考えPlaywrightで再試行する（world_market.pyと同じ方針）。
    """
    rows: list[dict] = []
    try:
        rows = parse_ranking_html(fetch(url))
    except Exception:
        rows = []
    if rows:
        return rows
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_selector("table", timeout=15_000)
            page.wait_for_timeout(1_500)
            rows = parse_ranking_html(page.content())
            browser.close()
    except Exception:
        return rows
    return rows


def main() -> None:
    now = datetime.now(JST)
    watched = load_watched_codes()
    rankings = {}
    errors = []
    for key, label, url in RANKINGS:
        try:
            rows = fetch_ranking(url)[:TOP_N]
        except Exception as exc:  # noqa: BLE001 - never let one ranking source crash the whole run
            rows = []
            errors.append(f"{key}: {type(exc).__name__}: {exc}")
        rankings[key] = {
            "label": label,
            "source_url": url,
            "items": annotate_watched(rows, watched),
        }

    payload = {
        "schema_version": "market-ranking-watch-1.0",
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "source": "Yahoo!ファイナンス 日本株ランキング（値上がり率/出来高急増率/売買代金上位）",
        "note": (
            "参考・未検証。MS2 RSSのリアルタイムデータではなくYahoo!ファイナンスの"
            "遅延/日次データ。$buy/$short判定・音声通知には一切使用しない。"
            "固定100銘柄ウォッチリストに無い銘柄はalready_watched=falseで示すのみで、"
            "ウォッチリストへの自動追加は行わない。"
        ),
        "rankings": rankings,
        "errors": errors,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
