"""Research cost model. Components stay separate.

Rakuten publishes several domestic-stock commission courses. This repository
does not know which course the account uses, and AI SHADOW does not send an
order. A published 0 yen course is therefore not the shadow commission.
Spread is the observed bid/ask width. Slippage is the fill versus the
printed price. Neither one fills in commission.
"""
from __future__ import annotations

FEE_UNKNOWN = "FEE_UNKNOWN"
EVIDENCE_URL = "https://www.rakuten-sec.co.jp/web/domestic/stock/commission.html"
FETCHED_AT = "2026-10-05"
TARIFF_VERSION = None
EFFECTIVE_FROM = None

# Names on the official page. None of these is selected for shadow net P&L.
CANDIDATE_COURSES = (
    {
        "course": "ゼロコース",
        "requires": "SOR（Rクロスを含む）の利用同意。注文を出さない shadow には適用しない。",
        "quantity_required": False,
    },
    {
        "course": "超割コース",
        "requires": "1回の約定代金。株数が null の shadow では代金を計算できない。",
        "quantity_required": True,
    },
    {
        "course": "いちにち定額コース",
        "requires": "当日と前営業日夜間の約定代金合計。shadow は約定代金を持たない。",
        "quantity_required": True,
    },
)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def fee_schedule() -> dict:
    """The official page is recorded and not applied."""
    return {
        "broker": "Rakuten Securities",
        "quote_source": "Rakuten MarketSpeed II RSS",
        "order_method": "NO_ORDER",
        "order_method_detail": "RssOrder is unimplemented. Shadow uses collector quote simulation.",
        "account_course": None,
        "commission_status": FEE_UNKNOWN,
        "commission_yen": None,
        "evidence_url": EVIDENCE_URL,
        "tariff_version": TARIFF_VERSION,
        "effective_from": EFFECTIVE_FROM,
        "fetched_at": FETCHED_AT,
        "candidate_courses": CANDIDATE_COURSES,
        "applied_to_live_sample": False,
        "applied_to_shadow_net": False,
        "real_submit_allowed": False,
    }


def shadow_commission():
    """Never a number. A missing tariff is not 0 yen."""
    return FEE_UNKNOWN


def observe_spread(bid, ask):
    """Bid/ask width in yen. A missing or crossed quote stays unknown, not 0."""
    bid_value = _number(bid)
    ask_value = _number(ask)
    if bid_value is None or ask_value is None or bid_value <= 0 or ask_value <= 0:
        return None
    if ask_value < bid_value:
        return None
    return ask_value - bid_value


def cost_components(*, entry_bid, entry_ask, exit_bid, exit_ask, entry_slippage, exit_slippage) -> dict:
    entry_spread = observe_spread(entry_bid, entry_ask)
    exit_spread = observe_spread(exit_bid, exit_ask)
    schedule = fee_schedule()
    return {
        "commission": FEE_UNKNOWN,
        "exchange_fee": FEE_UNKNOWN,
        "other_cost": FEE_UNKNOWN,
        "entry_spread": entry_spread,
        "exit_spread": exit_spread,
        "spread_status": "OBSERVED" if entry_spread is not None or exit_spread is not None else "UNOBSERVED",
        "entry_slippage": _number(entry_slippage),
        "exit_slippage": _number(exit_slippage),
        "evidence_url": schedule["evidence_url"],
        "tariff_version": schedule["tariff_version"],
        "effective_from": schedule["effective_from"],
        "fetched_at": schedule["fetched_at"],
        "applied_to_shadow_net": False,
        "real_submit_allowed": False,
    }
