"""scripts/shadow_fill_model.py

Entry Fill Model v0.1（GitHub Issue #18 Execution Stack Phase 5.0、
C-057-GPT comment 5707721299 対応）。

MARKET/LIMIT entry注文について、外部から渡されたpoint-in-time
`MarketObservation`だけを使い、決定論的にfillを評価する純粋関数群。
ネットワーク・MS2・Excel・brokerへは一切直接アクセスしない。発注も
一切行わない——ここにあるのは「もし出していたら何が起きたか」を
事後的に評価するためのShadow用モデルだけである。

## MarketObservation契約
呼び出し側が渡す辞書は最低限以下のフィールドを持つ：
    observed_at        timezone-aware datetime
    bid, ask            float
    bid_qty, ask_qty     float（現物株数量）
    last_trade_price     float
    last_trade_qty       float
    tick_size            float
    data_freshness       "OK" | "STALE" | "MISSING" | "FUTURE"
欠損・NaN・inf・bid>ask・非正値・naive timestamp・future observationは
推測補完せず、fill_confidence="UNOBSERVABLE"（no fill）へ倒す。

## Entry Fill Model v0.1の設計判断（C-057-GPT仕様の範囲内での明示的選択）
- MARKET BUY/SELLは常にtop-of-book（ask/bid）だけを参照し、そのfillは
  「表示されている気配に基づく推定」であって約定が確認されたわけでは
  ないため、fill_confidenceは`PROBABLE`とする（LIMITのtrade-through
  確認済みfillに使う`CERTAIN`とは区別する）。
- MARKETのavg_fill_priceは常にreference_price（ask/bid）と同値とし、
  v0.1では板の厚み以上のwalk-the-book slippageはモデル化しない
  （spread_yenは出力するが、fillそのもののslippage_yen/bpsは未モデル化
  としてNoneのまま——詳細はPhase 5.0.1 hardening節参照）。
- LIMITは「Shadow submit後のtrade observationのみ」を使う——
  `observation.observed_at <= submitted_at`のobservationは一切使わない。
  trade-throughで約定したとみなす場合もavg_fill_priceはlimit_price
  そのもの（trade printのより有利な価格ではなく）を使う、保守的な
  見積りとする。

## Phase 5.0.1 hardening（Blocker 3、C-057R-GPT comment 5707963859）
v0.1はL1（top-of-book）だけを見ており、MARKET partialの板walkや実約定
slippageを一切観測していない。にもかかわらずfill成立時に
`slippage_yen=0.0`/`slippage_bps=0.0`を書き込むと、「未モデル化」を
「ゼロslippage」として記録してしまい、将来のCalibration Reportが
Execution品質を過大評価する。v0.1でslippageを実測/推定していない
ケースは常に`None`のままとし、fillが成立した場合だけ
`slippage_model_status="NOT_MODELED_V0_1"`を明示する（fillしていない
場合はslippageの問い自体が成立しないため`slippage_model_status`も
`None`のまま）。
"""
from __future__ import annotations

import math
from datetime import datetime

FILL_MODEL_VERSION = "shadow-fill-model-0.1"
FILL_CONFIDENCES = ("CERTAIN", "PROBABLE", "UNCERTAIN", "UNOBSERVABLE")
DATA_FRESHNESS_VALUES = ("OK", "STALE", "MISSING", "FUTURE")
VALID_SIDES = ("BUY", "SELL")


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_finite_positive(value) -> bool:
    return _is_finite_number(value) and value > 0


def _is_finite_non_negative(value) -> bool:
    return _is_finite_number(value) and value >= 0


def validate_observation(observation, *, now: datetime) -> tuple[bool, list[str]]:
    """MarketObservationのshape・freshness・timestampをfail-closedで検証
    する純粋関数。使用可能ならTrueと空リスト、そうでなければFalseと
    理由コードのリストを返す（複数の問題があれば全て列挙する）。
    """
    reasons = []
    if not isinstance(observation, dict):
        return False, ["OBSERVATION_INVALID_TYPE"]
    if not isinstance(now, datetime) or now.tzinfo is None:
        reasons.append("NOW_NOT_TIMEZONE_AWARE")
    observed_at = observation.get("observed_at")
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        reasons.append("OBSERVATION_TIMESTAMP_NOT_TIMEZONE_AWARE")
    elif not reasons and observed_at > now:
        reasons.append("OBSERVATION_TIMESTAMP_FUTURE")
    freshness = observation.get("data_freshness")
    if freshness not in DATA_FRESHNESS_VALUES:
        reasons.append("OBSERVATION_FRESHNESS_UNKNOWN")
    elif freshness != "OK":
        reasons.append("OBSERVATION_FRESHNESS_" + freshness)
    bid, ask = observation.get("bid"), observation.get("ask")
    if not _is_finite_positive(bid) or not _is_finite_positive(ask):
        reasons.append("OBSERVATION_BID_ASK_INVALID")
    elif bid > ask:
        reasons.append("OBSERVATION_BID_ASK_CROSSED")
    tick_size = observation.get("tick_size")
    if not _is_finite_positive(tick_size):
        reasons.append("OBSERVATION_TICK_SIZE_INVALID")
    return (len(reasons) == 0), reasons


def _base_result(observation, *, reference_price=None, fill_confidence="UNOBSERVABLE",
                  fill_reason="UNOBSERVABLE") -> dict:
    best_bid = observation.get("bid") if isinstance(observation, dict) else None
    best_ask = observation.get("ask") if isinstance(observation, dict) else None
    bid_qty = observation.get("bid_qty") if isinstance(observation, dict) else None
    ask_qty = observation.get("ask_qty") if isinstance(observation, dict) else None
    best_bid = best_bid if _is_finite_number(best_bid) else None
    best_ask = best_ask if _is_finite_number(best_ask) else None
    spread_yen = (best_ask - best_bid) if (best_bid is not None and best_ask is not None) else None
    return {
        "filled_qty": 0,
        "reference_price": reference_price,
        "avg_fill_price": None,
        "fill_confidence": fill_confidence,
        "fill_reason": fill_reason,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_qty": bid_qty,
        "ask_qty": ask_qty,
        "spread_yen": spread_yen,
        # Phase 5.0.1 hardening（Blocker 3）: v0.1はslippageを実測/推定して
        # いないため、fillしていない限りNoneのまま——0.0を書いて「計測した
        # 結果ゼロだった」と誤解させない。
        "slippage_yen": None,
        "slippage_bps": None,
        "slippage_model_status": None,
    }


def evaluate_market_fill(*, side: str, requested_qty, observation: dict, now: datetime) -> dict:
    """MARKET entryのEntry Fill Model v0.1。BUYは`ask`/`ask_qty`、SELLは
    `bid`/`bid_qty`のみを参照する——mid/last_tradeは一切参照しない
    （Golden #8/#9）。可視数量が不足していれば可視分だけpartial fillとし、
    残数量を架空にfillしない（Golden #10）。
    """
    ok, reasons = validate_observation(observation, now=now)
    if not ok:
        return _base_result(observation, fill_reason=reasons[0])
    if side not in VALID_SIDES:
        return _base_result(observation, fill_reason="SIDE_INVALID")
    if not _is_finite_positive(requested_qty) or int(requested_qty) != requested_qty:
        return _base_result(observation, fill_reason="REQUESTED_QTY_INVALID")

    if side == "BUY":
        reference_price = observation["ask"]
        visible_qty = observation.get("ask_qty")
    else:
        reference_price = observation["bid"]
        visible_qty = observation.get("bid_qty")

    if not _is_finite_non_negative(visible_qty):
        return _base_result(observation, reference_price=reference_price, fill_reason="VISIBLE_QTY_UNAVAILABLE")

    filled_qty = int(min(int(requested_qty), int(visible_qty)))
    if filled_qty <= 0:
        return _base_result(observation, reference_price=reference_price, fill_reason="VISIBLE_QTY_ZERO")

    base = _base_result(observation, reference_price=reference_price)
    avg_fill_price = float(reference_price)
    reason = "FULL_FILL_VISIBLE_QTY_SUFFICIENT" if filled_qty >= int(requested_qty) else "PARTIAL_FILL_VISIBLE_QTY_ONLY"
    return {
        **base,
        "filled_qty": filled_qty,
        "avg_fill_price": avg_fill_price,
        "fill_confidence": "PROBABLE",
        "fill_reason": reason,
        "slippage_yen": None,
        "slippage_bps": None,
        "slippage_model_status": "NOT_MODELED_V0_1",
    }


def evaluate_limit_fill(*, side: str, requested_qty, limit_price, observation: dict, now: datetime,
                         submitted_at: datetime) -> dict:
    """LIMIT entryのEntry Fill Model v0.1。Shadow submit後のtrade
    observationのみを使う（`observed_at <= submitted_at`は使わない）。
    trade-throughはCERTAIN fill、limit価格ちょうどのtouchはUNCERTAINで
    確定fill扱いにしない、trade観測が無ければno fill（Golden #11-#13）。
    """
    ok, reasons = validate_observation(observation, now=now)
    if not ok:
        return _base_result(observation, fill_reason=reasons[0])
    if side not in VALID_SIDES:
        return _base_result(observation, fill_reason="SIDE_INVALID")
    if not _is_finite_positive(requested_qty) or int(requested_qty) != requested_qty:
        return _base_result(observation, fill_reason="REQUESTED_QTY_INVALID")
    if not _is_finite_positive(limit_price):
        return _base_result(observation, fill_reason="LIMIT_PRICE_INVALID")
    if not isinstance(submitted_at, datetime) or submitted_at.tzinfo is None:
        return _base_result(observation, fill_reason="SUBMITTED_AT_NOT_TIMEZONE_AWARE")

    observed_at = observation["observed_at"]
    if observed_at <= submitted_at:
        return _base_result(observation, reference_price=float(limit_price), fill_reason="OBSERVATION_BEFORE_SUBMISSION")

    last_trade_price = observation.get("last_trade_price")
    if not _is_finite_positive(last_trade_price):
        return _base_result(observation, reference_price=float(limit_price), fill_reason="NO_POST_SUBMIT_TRADE")

    if side == "BUY":
        if last_trade_price < limit_price:
            reason, confidence, filled = "TRADE_THROUGH", "CERTAIN", True
        elif last_trade_price == limit_price:
            reason, confidence, filled = "TOUCH_ONLY", "UNCERTAIN", False
        else:
            reason, confidence, filled = "NO_TRADE_AT_OR_THROUGH_LIMIT", "CERTAIN", False
    else:  # SELL
        if last_trade_price > limit_price:
            reason, confidence, filled = "TRADE_THROUGH", "CERTAIN", True
        elif last_trade_price == limit_price:
            reason, confidence, filled = "TOUCH_ONLY", "UNCERTAIN", False
        else:
            reason, confidence, filled = "NO_TRADE_AT_OR_THROUGH_LIMIT", "CERTAIN", False

    base = _base_result(observation, reference_price=float(limit_price), fill_confidence=confidence, fill_reason=reason)
    if not filled:
        return base

    filled_qty = int(requested_qty)
    avg_fill_price = float(limit_price)
    return {
        **base,
        "filled_qty": filled_qty,
        "avg_fill_price": avg_fill_price,
        "slippage_yen": None,
        "slippage_bps": None,
        "slippage_model_status": "NOT_MODELED_V0_1",
    }
