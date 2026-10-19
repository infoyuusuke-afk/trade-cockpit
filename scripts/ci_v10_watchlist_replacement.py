"""CI check: the V10 watchlist differs from the pinned source by exactly the
OWNER-approved replacement and nothing else.

OWNER approval (2026-10-19): QPS研究所 5595.T was delisted on 2025-11-27 and
replaced 1:1 by QPSホールディングス 464A.T (TSE Growth, listed 2025-12-01).
This is not a general source-pin bypass: any other difference fails.

Usage: python scripts/ci_v10_watchlist_replacement.py <candidate.json> <pinned.json>
"""
from __future__ import annotations

import json
import sys

APPROVED_OLD = ("QPS研究所（5595）", "5595.T")
APPROVED_NEW = ("QPSホールディングス（464A）", "464A.T")
EXPECTED_COUNT = 100


class WatchlistReplacementError(AssertionError):
    pass


def _fail(code: str) -> None:
    raise WatchlistReplacementError(code)


def check_replacement(candidate: dict, pinned: dict) -> None:
    """Raise WatchlistReplacementError(code) unless exactly the approved change."""
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
    if len(changed) != 1:
        _fail("WATCHLIST_CHANGE_COUNT_NOT_ONE")
    (old_name, old_row), (new_name, new_row) = changed[0]
    if (old_name, old_row.get("ticker")) != APPROVED_OLD or (new_name, new_row.get("ticker")) != APPROVED_NEW:
        _fail("WATCHLIST_UNAPPROVED_REPLACEMENT")
    if set(old_row) != set(new_row):
        _fail("WATCHLIST_FIELDS_CHANGED")
    if any(old_row[k] != new_row[k] for k in old_row if k != "ticker"):
        _fail("WATCHLIST_OTHER_ATTRIBUTES_CHANGED")


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
        print("OWNER_APPROVED_SINGLE_WATCHLIST_REPLACEMENT=FAIL " + str(exc))
        return 1
    print("OWNER_APPROVED_SINGLE_WATCHLIST_REPLACEMENT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
