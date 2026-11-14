"""CI check: the V10 watchlist differs from the pinned source by exactly the
OWNER-approved replacements and nothing else.

OWNER approvals:
- 2026-10-19: QPS研究所 5595.T was delisted on 2025-11-27 and replaced 1:1 by
  QPSホールディングス 464A.T.
- 2026-10-21 00:45 JST (P0-V10-INTEGRATION-AND-LIVE-START-20261020, "15銘柄いれかえOK"):
  the 15 thinnest rows (most often without a trade for 120 s on 10/16, 10/19
  and 10/20) are replaced in place by liquid stocks. 464A.T is one of them, so
  the pinned 5595.T row now becomes 9983.T.

Each approved row must stay at its original position with exactly the listed
name, ticker, sector and style. This is not a general source-pin bypass: any
other difference fails.

Usage: python scripts/ci_v10_watchlist_replacement.py <candidate.json> <pinned.json>
"""
from __future__ import annotations

import json
import sys

# (pinned name, pinned ticker) -> (new name, exact new row)
APPROVED = {
    ("FIXER（5129）", "5129.T"): ("太陽誘電（6976）", {"ticker": "6976.T", "sector": "電子部品・AI", "style": "day"}),
    ("チャットプラス（598A）", "598A.T"): ("イビデン（4062）", {"ticker": "4062.T", "sector": "半導体・AI", "style": "day"}),
    ("フューチャー（4722）", "4722.T"): ("村田製作所（6981）", {"ticker": "6981.T", "sector": "電子部品・AI", "style": "day"}),
    ("モビルス（4370）", "4370.T"): ("みずほFG（8411）", {"ticker": "8411.T", "sector": "銀行・金利", "style": "day"}),
    ("QPS研究所（5595）", "5595.T"): ("ファーストリテイリング（9983）", {"ticker": "9983.T", "sector": "小売・値がさ", "style": "day"}),
    ("ユアテック（1934）", "1934.T"): ("JX金属（5016）", {"ticker": "5016.T", "sector": "非鉄・レアメタル", "style": "day"}),
    ("アイサンテクノロジー（4667）", "4667.T"): ("レゾナックHD（4004）", {"ticker": "4004.T", "sector": "半導体・素材", "style": "day"}),
    ("プレイド（4165）", "4165.T"): ("三井金属（5706）", {"ticker": "5706.T", "sector": "非鉄・レアメタル", "style": "day"}),
    ("FRONTEO（2158）", "2158.T"): ("KOKUSAI ELECTRIC（6525）", {"ticker": "6525.T", "sector": "半導体・AI", "style": "day"}),
    ("ワークマン（7564）", "7564.T"): ("日本製鉄（5401）", {"ticker": "5401.T", "sector": "鉄鋼・素材", "style": "day"}),
    ("セリア（2782）", "2782.T"): ("ルネサス（6723）", {"ticker": "6723.T", "sector": "半導体・AI", "style": "day"}),
    ("さくらインターネット（3778）", "3778.T"): ("HOYA（7741）", {"ticker": "7741.T", "sector": "半導体・素材", "style": "day"}),
    ("セルシス（3663）", "3663.T"): ("東京海上HD（8766）", {"ticker": "8766.T", "sector": "保険・金利", "style": "day"}),
    ("ハーモニック・ドライブ・システムズ（6324）", "6324.T"): ("伊藤忠商事（8001）", {"ticker": "8001.T", "sector": "商社・資源", "style": "day"}),
    ("freee（4478）", "4478.T"): ("りそなHD（8308）", {"ticker": "8308.T", "sector": "銀行・金利", "style": "day"}),
}
EXPECTED_COUNT = 100


class WatchlistReplacementError(AssertionError):
    pass


def _fail(code: str) -> None:
    raise WatchlistReplacementError(code)


def check_replacement(candidate: dict, pinned: dict) -> None:
    """Raise WatchlistReplacementError(code) unless exactly the approved changes."""
    if not isinstance(candidate, dict) or not isinstance(pinned, dict):
        _fail("WATCHLIST_NOT_OBJECT")
    if set(candidate) != set(pinned):
        _fail("WATCHLIST_TOP_LEVEL_CHANGED")
    for key in candidate:
        if key != "stocks" and candidate[key] != pinned[key]:
            _fail("WATCHLIST_UNRELATED_CHANGE:" + key)
    if not isinstance(candidate.get("stocks"), dict) or not isinstance(pinned.get("stocks"), dict):
        _fail("WATCHLIST_STOCKS_NOT_OBJECT")
    old = list(pinned["stocks"].items())
    new = list(candidate["stocks"].items())
    if len(old) != EXPECTED_COUNT or len(new) != EXPECTED_COUNT:
        _fail("WATCHLIST_COUNT_CHANGED")
    tickers = [row.get("ticker") if isinstance(row, dict) else None for _, row in new]
    if not all(isinstance(t, str) and t for t in tickers):
        _fail("WATCHLIST_INVALID_TICKER")
    if len(tickers) != len(set(tickers)):
        _fail("WATCHLIST_DUPLICATE_TICKER")
    changed = [(a, b) for a, b in zip(old, new) if a != b]
    if len(changed) != len(APPROVED):
        _fail("WATCHLIST_CHANGE_COUNT_NOT_APPROVED")
    seen = set()
    for (old_name, old_row), (new_name, new_row) in changed:
        key = (old_name, old_row.get("ticker") if isinstance(old_row, dict) else None)
        if key not in APPROVED or key in seen:
            _fail("WATCHLIST_UNAPPROVED_REPLACEMENT")
        seen.add(key)
        want_name, want_row = APPROVED[key]
        if new_name != want_name or new_row != want_row:
            _fail("WATCHLIST_UNAPPROVED_REPLACEMENT")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: ci_v10_watchlist_replacement.py <candidate.json> <pinned.json>")
        return 2
    with open(argv[1], encoding="utf-8-sig") as fh:
        candidate = json.load(fh)
    with open(argv[2], encoding="utf-8-sig") as fh:
        pinned = json.load(fh)
    try:
        check_replacement(candidate, pinned)
    except WatchlistReplacementError as exc:
        print("OWNER_APPROVED_WATCHLIST_REPLACEMENT=FAIL " + str(exc))
        return 1
    print("OWNER_APPROVED_WATCHLIST_REPLACEMENT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
