"""scripts/tradingview_screener_watch.py

TradingViewスクリーナーを使った外部ランキング発掘（C-041/C-042の続き）。
`scripts/market_ranking_watch.py`（Yahoo!ファイナンス版）とは意図的に完全に独立した別
ファイルにしている。ユーザー指示（2026-09-17）：「ブロックされたら困るから、今のはこのまま
残して新しくつくりなおしたい」——つまりこの2つは互いのフォールバックであり、どちらか一方の
エンドポイントが将来ブロック・仕様変更されても、もう一方は影響を受けない設計にする。

## 経緯・検証
`scanner.tradingview.com/{market}/scan` はTradingView非公式（ただし同社の自社サイトの
スクリーナーUI自体が使っている、コミュニティでも広く使われている）JSON APIで、認証不要。
2026-09-17に実機でPOSTリクエストを送り、日本市場（`markets:["japan"]`）から
`name`(銘柄コード)・`description`(会社名)・`close`・`volume`・`change`(前日比%)・
`relative_volume_10d_calc`(相対出来高)・`ATR`・`VWAP`・`high`・`low`・
`market_cap_basic`・`sector`・`exchange` の13列を1回のリクエストで取得できることを
確認済み（列数・順序とも一致、フィールド名の誤りは無言でずれるため実機で1件ずつ検証した）。

Yahoo!ファイナンス版との比較（ユーザー確認済み・共有シートC-044参照）：
- Yahoo: HTML依存・ランキング種別ごとに別ページ・項目は価格/前日比/出来高のみ
- TradingView: 構造化JSON・1リクエストで複合条件フィルタ+ソート・ATR/VWAP/相対出来高も取得可

## 正直な制約
- 非公式・無保証のエンドポイント。ToS上の位置づけは不明確で、将来ブロック・仕様変更の
  リスクがある（だからこそYahoo版を並存させる設計にしている）。
- 過度なリクエストを避けるため、1回の実行で行う実際のHTTPリクエストは1回だけに抑え、
  複数の「ランキング」はこの1回の取得データをPython側で並べ替えるだけで作る。
- 参考・未検証。MS2 RSSのリアルタイムデータではないため、$buy/$short判定・音声通知には
  一切使用しない。ウォッチリストへの自動追加も行わない。
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
WATCHLIST_PATH = ROOT / "ms2_live" / "watchlist_100.json"
OUT_PATH = ROOT / "tradingview_screener_watch.json"

SCAN_URL = "https://scanner.tradingview.com/japan/scan"
COLUMNS = [
    "name", "description", "close", "volume", "change",
    "relative_volume_10d_calc", "ATR", "VWAP", "high", "low",
    "market_cap_basic", "sector", "exchange",
]
MIN_VOLUME = 1_000_000
FETCH_LIMIT = 300  # 出来高上位300銘柄のみ取得（リクエスト1回・payloadを抑える）
TOP_N = 20


def fetch_screener(min_volume: int = MIN_VOLUME, limit: int = FETCH_LIMIT) -> list[dict]:
    """TradingViewスクリーナーへ1回だけPOSTし、行のリストを返す（fetchとパースを分離）。"""
    body = json.dumps({
        "markets": ["japan"],
        "columns": COLUMNS,
        "filter": [{"left": "volume", "operation": "greater", "right": min_volume}],
        "sort": {"sortBy": "volume", "sortOrder": "desc"},
        "range": [0, limit],
    }).encode("utf-8")
    req = urllib.request.Request(
        SCAN_URL, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 trade-cockpit-public-screener/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read())
    return parse_scan_response(payload)


def parse_scan_response(payload: dict) -> list[dict]:
    """TradingViewのレスポンスJSONを行の辞書リストへ変換する純粋関数（テスト対象）。
    列の並びはCOLUMNSと一致している前提（実機で列数一致を確認済み）。列数が合わない行は
    推定で埋めず、その行だけスキップする（記録として残せない値を捏造しない）。
    """
    rows = []
    for entry in (payload or {}).get("data") or []:
        values = entry.get("d") or []
        if len(values) != len(COLUMNS):
            continue
        row = dict(zip(COLUMNS, values))
        code = str(row.get("name") or "")
        close = row.get("close")
        atr_pct = None
        if isinstance(row.get("ATR"), (int, float)) and isinstance(close, (int, float)) and close:
            atr_pct = round(row["ATR"] / close * 100, 2)
        rows.append({
            "code": code,
            "name": row.get("description"),
            "exchange": row.get("exchange"),
            "price": close,
            "change_pct": row.get("change"),
            "volume": row.get("volume"),
            "relative_volume": row.get("relative_volume_10d_calc"),
            "atr_pct": atr_pct,
            "vwap": row.get("VWAP"),
            "high": row.get("high"),
            "low": row.get("low"),
            "market_cap": row.get("market_cap_basic"),
            "sector": row.get("sector"),
        })
    return rows


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


def build_rankings(rows: list[dict], top_n: int = TOP_N) -> dict:
    """1回の取得データから複数のランキングをPython側で作る純粋関数（テスト対象）。
    追加のHTTPリクエストは発生させない（ブロック回避のため実リクエストは1回に抑える方針）。
    """
    numeric = lambda key: lambda x: x.get(key) if isinstance(x.get(key), (int, float)) else float("-inf")
    gainers = sorted(rows, key=numeric("change_pct"), reverse=True)[:top_n]
    decliners = sorted(rows, key=numeric("change_pct"))[:top_n]
    volume_surge = sorted(rows, key=numeric("relative_volume"), reverse=True)[:top_n]
    high_atr = sorted(rows, key=numeric("atr_pct"), reverse=True)[:top_n]
    turnover = sorted(
        rows,
        key=lambda x: (x.get("price") or 0) * (x.get("volume") or 0),
        reverse=True,
    )[:top_n]
    return {
        "up": {"label": "値上がり率", "items": gainers},
        "down": {"label": "値下がり率", "items": decliners},
        "volume_surge": {"label": "出来高急増（相対出来高）", "items": volume_surge},
        "high_atr": {"label": "ATR比率上位（値動きの荒さ）", "items": high_atr},
        "turnover": {"label": "売買代金上位（概算）", "items": turnover},
    }


def main() -> None:
    now = datetime.now(JST)
    watched = load_watched_codes()
    error = None
    rankings: dict = {}
    try:
        rows = fetch_screener()
        rows = annotate_watched(rows, watched)
        rankings = build_rankings(rows)
    except Exception as exc:  # noqa: BLE001 - never let this crash the pipeline
        error = f"{type(exc).__name__}: {exc}"

    payload = {
        "schema_version": "tradingview-screener-watch-1.0",
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "source": "TradingViewスクリーナー（非公式・無保証API、scanner.tradingview.com）",
        "note": (
            "参考・未検証。MS2 RSSのリアルタイムデータではない。$buy/$short判定・音声通知には"
            "一切使用しない。固定100銘柄ウォッチリストに無い銘柄はalready_watched=falseで"
            "示すのみで、ウォッチリストへの自動追加は行わない。market_ranking_watch.py"
            "（Yahoo!ファイナンス版）とは独立した別実装で、互いのフォールバックとして併存させる。"
        ),
        "rankings": rankings,
        "error": error,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
