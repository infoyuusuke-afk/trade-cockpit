"""TSE daily price-limit helpers for previous-session limit-up/down research.

The normal price-limit table follows JPX domestic stock trading rules.
Expanded limits are exceptional and must be supplied as explicit overrides after
checking the official JPX broadened-limit notice. The module never guesses an
expanded limit.

This module does not enable trading. It only normalizes previous-session evidence
for EVENT 5.
"""
from __future__ import annotations

from typing import Optional

# Exclusive upper bound of base price -> normal one-sided limit width (yen).
# The final tuple with None covers 50,000,000 yen or more.
NORMAL_LIMIT_TABLE = [
    (100, 30),
    (200, 50),
    (500, 80),
    (700, 100),
    (1_000, 150),
    (1_500, 300),
    (2_000, 400),
    (3_000, 500),
    (5_000, 700),
    (7_000, 1_000),
    (10_000, 1_500),
    (15_000, 3_000),
    (20_000, 4_000),
    (30_000, 5_000),
    (50_000, 7_000),
    (70_000, 10_000),
    (100_000, 15_000),
    (150_000, 30_000),
    (200_000, 40_000),
    (300_000, 50_000),
    (500_000, 70_000),
    (700_000, 100_000),
    (1_000_000, 150_000),
    (1_500_000, 300_000),
    (2_000_000, 400_000),
    (3_000_000, 500_000),
    (5_000_000, 700_000),
    (7_000_000, 1_000_000),
    (10_000_000, 1_500_000),
    (15_000_000, 3_000_000),
    (20_000_000, 4_000_000),
    (30_000_000, 5_000_000),
    (50_000_000, 7_000_000),
    (None, 10_000_000),
]


def _num(value) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        if result != result:
            return None
        return result
    except (TypeError, ValueError):
        return None


def normal_limit_width(base_price: float) -> float:
    base = _num(base_price)
    if base is None or base <= 0:
        raise ValueError("base_price must be positive")

    for upper_bound, width in NORMAL_LIMIT_TABLE:
        if upper_bound is None or base < upper_bound:
            return float(width)
    raise AssertionError("unreachable")


def daily_limit_prices(
    base_price: float,
    *,
    upper_width_override: Optional[float] = None,
    lower_width_override: Optional[float] = None,
) -> dict:
    base = _num(base_price)
    if base is None or base <= 0:
        raise ValueError("base_price must be positive")

    normal = normal_limit_width(base)
    upper_width = _num(upper_width_override)
    lower_width = _num(lower_width_override)

    if upper_width is None:
        upper_width = normal
    if lower_width is None:
        lower_width = normal
    if upper_width <= 0 or lower_width <= 0:
        raise ValueError("limit widths must be positive")

    return {
        "base_price": base,
        "normal_width": normal,
        "upper_width": upper_width,
        "lower_width": lower_width,
        "upper_limit": base + upper_width,
        "lower_limit": max(1.0, base - lower_width),
        "expanded_upper": upper_width != normal,
        "expanded_lower": lower_width != normal,
    }


def detect_limit_event(
    *,
    base_price: float,
    high: Optional[float],
    low: Optional[float],
    close: Optional[float],
    final_quote: Optional[float] = None,
    upper_width_override: Optional[float] = None,
    lower_width_override: Optional[float] = None,
    official_override_checked: bool = False,
    tolerance: float = 1e-9,
) -> dict:
    limits = daily_limit_prices(
        base_price,
        upper_width_override=upper_width_override,
        lower_width_override=lower_width_override,
    )

    high_v = _num(high)
    low_v = _num(low)
    close_v = _num(close)
    quote_v = _num(final_quote)

    upper = limits["upper_limit"]
    lower = limits["lower_limit"]

    touched_upper = high_v is not None and high_v >= upper - tolerance
    touched_lower = low_v is not None and low_v <= lower + tolerance
    closed_upper = close_v is not None and abs(close_v - upper) <= tolerance
    closed_lower = close_v is not None and abs(close_v - lower) <= tolerance
    quoted_upper = quote_v is not None and abs(quote_v - upper) <= tolerance
    quoted_lower = quote_v is not None and abs(quote_v - lower) <= tolerance

    if closed_upper or quoted_upper:
        side = "UP"
    elif closed_lower or quoted_lower:
        side = "DOWN"
    elif touched_upper:
        side = "UP_TOUCH"
    elif touched_lower:
        side = "DOWN_TOUCH"
    else:
        side = "NONE"

    expanded = bool(limits["expanded_upper"] or limits["expanded_lower"])

    if side == "NONE":
        event_state = "NONE"
        verification_status = "NO_LIMIT_EVENT"
    elif expanded:
        # Explicit override means caller supplied the exceptional width.
        event_state = (
            "LIMIT_UP" if side == "UP"
            else "LIMIT_DOWN" if side == "DOWN"
            else "LIMIT_UP_TOUCH" if side == "UP_TOUCH"
            else "LIMIT_DOWN_TOUCH"
        )
        verification_status = "OFFICIAL_OVERRIDE_APPLIED"
    elif official_override_checked:
        event_state = (
            "LIMIT_UP" if side == "UP"
            else "LIMIT_DOWN" if side == "DOWN"
            else "LIMIT_UP_TOUCH" if side == "UP_TOUCH"
            else "LIMIT_DOWN_TOUCH"
        )
        verification_status = "NORMAL_LIMIT_CONFIRMED"
    else:
        # A normal-table hit can be wrong for a broadened-limit issue. Keep it
        # as potential evidence until the official exceptional list is checked.
        event_state = (
            "POTENTIAL_LIMIT_UP" if side == "UP"
            else "POTENTIAL_LIMIT_DOWN" if side == "DOWN"
            else "POTENTIAL_LIMIT_UP_TOUCH" if side == "UP_TOUCH"
            else "POTENTIAL_LIMIT_DOWN_TOUCH"
        )
        verification_status = "EXPANSION_CHECK_REQUIRED"

    return {
        **limits,
        "event_state": event_state,
        "verification_status": verification_status,
        "official_override_checked": bool(official_override_checked),
        "high": high_v,
        "low": low_v,
        "close": close_v,
        "final_quote": quote_v,
        "touched_upper": touched_upper,
        "touched_lower": touched_lower,
        "closed_upper": closed_upper,
        "closed_lower": closed_lower,
        "quoted_upper": quoted_upper,
        "quoted_lower": quoted_lower,
    }
