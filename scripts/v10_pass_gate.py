#!/usr/bin/env python3
"""The one pass gate for a trading method. Research only: it reads a trade list and returns a verdict.

OWNER 2026-11-06 「合格の4条件を、一つの関数（一つの門）にまとめる。4つ全部を通った手法だけを『合格』にする」:
  1 count   : at least 30 closed trades. An open trade or a marked-to-market value is never counted.
  2 mean    : the mean after cost is above zero. Cost = commission + slippage (at least one tick
              on each side) + interest or stock-lending fee.
  3 random  : OWNER 2026-11-07 「ランダム比較：向きの入れ替えは残すが、合格の条件には使わない」: the method's mean must beat
              at least 95% of random entry times on the same day and stock. That test does not exist yet, so a caller
              passes random_time_share; until then this condition fails and nothing can be 合格. The swapped-direction
              share is still reported as direction_share, and is not a condition.
  4 periods : the mean after cost is above zero in the first half and in the second half of the days.

A trade is a dict: status, day, side (1 or -1), gross_pct (signed for the trade), price, and cost_pct
(round-trip commission and financing in percent, before slippage). No field defaults: a trade that
lacks one is reported as invalid, and an invalid list cannot pass. Nothing here places an order.
"""
from __future__ import annotations

import bisect
import random

MIN_CLOSED = 30
PERMUTATIONS = 10000
CONFIDENCE = 0.95
MIN_SLIPPAGE_TICKS_PER_SIDE = 1
CLOSED = "CLOSED"
# The ordinary TSE tick table. A TOPIX 500 stock can have a finer tick, so this is the cautious side.
TICKS = ((3000, 1), (5000, 5), (30000, 10), (50000, 50), (300000, 100), (500000, 500), (3000000, 1000), (5000000, 5000))


def tick_size(price: float) -> float:
    for limit, tick in TICKS:
        if price <= limit:
            return tick
    return 10000


def net_pct(trade: dict, slippage_ticks: int = MIN_SLIPPAGE_TICKS_PER_SIDE) -> float:
    """The trade's return after commission, financing and slippage on both sides, in percent."""
    price = float(trade["price"])
    slip = 2 * max(slippage_ticks, MIN_SLIPPAGE_TICKS_PER_SIDE) * tick_size(price) / price * 100
    return float(trade["gross_pct"]) - float(trade["cost_pct"]) - slip


def _valid(trade: dict) -> bool:
    try:
        return (trade["side"] in (1, -1) and float(trade["price"]) > 0 and bool(trade["day"])
                and float(trade["cost_pct"]) >= 0 and isinstance(float(trade["gross_pct"]), float))
    except (KeyError, TypeError, ValueError):
        return False


def closed_trades(trades: list[dict]) -> list[dict]:
    return [t for t in trades if t.get("status") == CLOSED]


def profit_factor(values: list[float]) -> float | None:
    """None when there is no loss to divide by. Zero is neither a win nor a loss."""
    win = sum(v for v in values if v > 0)
    loss = -sum(v for v in values if v < 0)
    return round(win / loss, 2) if loss > 0 else None


def permutation_share(trades: list[dict], seed: int = 20261106, rounds: int = PERMUTATIONS) -> float:
    """The share of random-direction means that the real mean beats (ties count against it)."""
    n = len(trades)
    if not n:
        return 0.0
    gross = [float(t["gross_pct"]) for t in trades]
    drag = [float(t["gross_pct"]) - net_pct(t) for t in trades]
    real = sum(g - d for g, d in zip(gross, drag)) / n
    rng = random.Random(seed)
    beaten = 0
    for _ in range(rounds):
        mean = sum((g if rng.random() < .5 else -g) - d for g, d in zip(gross, drag)) / n
        beaten += real > mean
    return beaten / rounds


def _seconds(clock: str) -> int:
    return int(clock[:2]) * 3600 + int(clock[3:5]) * 60 + int(clock[6:8])


def _random_return(secs: list, prices: list, hold: int, side: int, rng: random.Random) -> float:
    """Enter at a random print of the same day and stock, hold for the same time, in the same direction."""
    at = rng.randrange(len(secs))
    out = min(bisect.bisect_left(secs, secs[at] + hold, at), len(secs) - 1)
    return side * (prices[out] / prices[at] - 1) * 100


def random_time_share(trades: list[dict], seed: int = 20261108, rounds: int = 2000) -> float | None:
    """OWNER 2026-11-07 「時刻の検査は research/pass-gate で作る」: the share of random-entry means that the real mean beats
    (ties count against it). Same day, stock, direction, hold time and cost as each trade; stops and targets are not
    replayed, so the random side only keeps the time. None when any trade has no price path: an untested list cannot pass."""
    if not trades or any(not t.get("path") or t.get("hold_s") is None for t in trades):
        return None
    n = len(trades)
    drag = [float(t["gross_pct"]) - net_pct(t) for t in trades]
    real = sum(net_pct(t) for t in trades) / n
    rows = [([_seconds(c) for c, _ in t["path"]], [p for _, p in t["path"]], int(t["hold_s"]), int(t["side"]), d) for t, d in zip(trades, drag)]
    rng = random.Random(seed)
    beaten = 0
    for _ in range(rounds):
        mean = sum(_random_return(s, p, h, side, rng) - d for s, p, h, side, d in rows) / n
        beaten += real > mean
    return beaten / rounds


def split_by_day(trades: list[dict], calendar: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Two halves of the days, the earlier half smaller when the count is odd. The days are the trades' own days,
    or the shared calendar when one is given (the way the 11/6 check cut every rule at the same day)."""
    days = sorted(set(calendar) if calendar else {str(t["day"]) for t in trades})
    cut = days[len(days) // 2] if len(days) > 1 else None
    if cut is None:
        return list(trades), []
    return [t for t in trades if str(t["day"]) < cut], [t for t in trades if str(t["day"]) >= cut]


def evaluate(trades: list[dict], *, random_time_share: float | None = None, calendar: list[str] | None = None) -> dict:
    closed = closed_trades(trades)
    invalid = sum(not _valid(t) for t in closed)
    usable = [t for t in closed if _valid(t)]
    values = [net_pct(t) for t in usable]
    mean = sum(values) / len(values) if values else None
    first, second = split_by_day(usable, calendar)
    avg = lambda part: sum(net_pct(t) for t in part) / len(part) if part else None
    a, b = avg(first), avg(second)
    direction = permutation_share(usable)
    checks = {
        "count": len(usable) >= MIN_CLOSED and invalid == 0,
        "mean": mean is not None and mean > 0,
        "random": random_time_share is not None and random_time_share >= CONFIDENCE,
        "periods": a is not None and b is not None and a > 0 and b > 0,
    }
    failed = [k for k, ok in checks.items() if not ok]
    return {
        "passed": not failed, "label": "合格" if not failed else "不合格", "failed": failed, "checks": checks,
        "closed": len(closed), "open_ignored": len(trades) - len(closed), "invalid": invalid,
        "mean_net_pct": None if mean is None else round(mean, 4), "pf_net": profit_factor(values),
        "win_pct": round(100 * sum(v > 0 for v in values) / len(values), 1) if values else None,
        "random_time_share": random_time_share, "random_tested": random_time_share is not None, "direction_share": round(direction, 4), "first_half": {"n": len(first), "mean_net_pct": None if a is None else round(a, 4)},
        "second_half": {"n": len(second), "mean_net_pct": None if b is None else round(b, 4)},
    }
