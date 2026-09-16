"""scripts/risk_gate.py

Position Sizing / Risk Gate（GitHub Issue #18 Execution Stack Phase 3、
C-050-GPT comment 5703809332 + Phase 3.1 hardening C-050R-GPT comment
5703948448への対応）。

Conflict Resolver（scripts/conflict_resolver.py）が出力するResolvedScenario
（原則resolved_status=="CANDIDATE_READY"）を受け取り、数量（allowed_qty）を
決めるだけの純粋関数レイヤー。発注は一切行わない。broker/Excel/RSS/private
ledger/networkへ直接取りに行かず、必要な値は全て引数として受け取る。

## Canonical順序（C-050-GPTで確定）
    Signal → Conflict Resolver → Risk Gate（数量決定）
      → execution_contract.build_intent()（canonical intent_hashを初めて生成）
      → Phase 4 Permission / Kill / Duplicate Guard

**Risk Gateへcanonical `intent_hash`を入力しない／生成しない。** 現行の
canonical intent_hash（scripts/execution_contract.py）はquantityをhash対象に
含んでおり、数量決定前に存在すると循環依存になる。Risk Gateは
Conflict Resolverの`merge_hash`を上流scenarioの識別子（lineage key）として
そのまま保持するだけにする。

## 発注許可について
Risk Gateは`real_submit_allowed`というフィールドを一切作らない・出力しない
（trueにしない、ではなくそもそも出力しない）。発注可否はPhase 4の責務。
`scripts/execution_contract.py`のreal_submit_allowed=False固定・
`scripts/signal_contract.py`のtrading_enabled=False固定は、このファイルでは
一切変更しない。

## 判定語彙
`ALLOW`という語は自動発注許可と誤読しやすいため使わない。
- `PASS`: risk/sizing上のみ通過。発注許可ではない。
- `SHADOW_ONLY`: strategy/scenario自体は研究継続できるが、30万円Real lane
  では0株（例: risk budget超過、cash不足、daily stop到達、
  max_open_positions到達、regime multiplier=0、CASH modeでの新規SELL）。
- `BLOCK`: malformed/stale/contradictory入力等でRisk計算自体を信用しない
  （resolved_status不一致、数値異常、stop方向不正、lot_size不明、policy
  自体が壊れている 等）。

## Phase 3.1 hardening（3 blocker、C-050R-GPT）
1. `test_capital_yen`（30万円）がnotional上限として効いていなかった。
   従来の`max_lots_by_cash`は`available_cash_yen`だけを見ており、実口座の
   余力が30万円を超えていると30万円テスト資金を超える建玉がPASSしえた。
   投下可能現金を`min(available_cash_yen, test_capital_yen)`でcapしてから
   fees_bufferを引く（entry*allowed_qty + feesが常に30万円以内になる）。
2. v0.1 policyが壊れた/未対応値になった場合の一部fail-openを解消。
   `validate_policy_v0_1()`でaccount_mode（CASH以外は未対応）・
   margin_leverage/averaging_down/flip/pyramiding（Falseでなければ不可）・
   数値項目（非数値・非正値）・max_open_positions（正整数でない）を検査し、
   1つでも違反があれば例外を投げずBLOCKで返す。将来MARGINを許可する場合は
   policy versionを上げて別途実装する（v0.1の設定変更だけで売買範囲が
   広がらないようにする）。
3. symbol・merge_hashの必須値検証、available_cash_yenの負値拒否、
   open_positions_countが0以上の整数であることの検証を追加。

## Phase 4へ送らないもの（意図的に扱わない）
DUPLICATE_INTENT_HASH・REAL_ORDER_PERMISSION_FALSE・KILL_SWITCH_ACTIVE・
BROKER_LINK_HEALTH・SHORT_AVAILABILITY・ORDER_PRICE_OUT_OF_TICK・ACK/
reconciliation系は全てPhase 4（未実装）の責務。canonical intent_hashは
Risk Gateの後段で生成されるため、ここでは扱えない。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

JST = timezone(timedelta(hours=9))
SCHEMA_VERSION = "risk-gate-1.1"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = ROOT / "config" / "risk_gate_v0_1.json"

VALID_SIDES = ("BUY", "SELL")
DECISIONS = ("PASS", "SHADOW_ONLY", "BLOCK")


def now_jst() -> datetime:
    return datetime.now(JST)


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict:
    """risk_gate_v0_1.jsonを読む（I/Oはここだけに閉じ込める。evaluate_risk()
    自体は純粋関数のまま、policyはdictで受け取る）。"""
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_positive_finite_number(value) -> bool:
    return _is_finite_number(value) and value > 0


def validate_policy_v0_1(policy: dict) -> list[str]:
    """v0.1 policyが安全境界の前提を満たしているか検証する純粋関数。
    キー欠損はKeyErrorを送出せず`.get()`で拾い、違反として報告する
    （C-050R-GPT Blocker 2: 壊れたpolicyがfail-openにならないようにする）。
    違反が無ければ空リストを返す。
    """
    violations = []
    if policy.get("account_mode") != "CASH":
        violations.append("BLOCK_POLICY_UNSUPPORTED_ACCOUNT_MODE")
    if policy.get("allow_margin_leverage") is not False:
        violations.append("BLOCK_POLICY_MARGIN_LEVERAGE_NOT_ALLOWED")
    if policy.get("allow_averaging_down") is not False:
        violations.append("BLOCK_POLICY_AVERAGING_DOWN_NOT_ALLOWED")
    if policy.get("allow_flip") is not False:
        violations.append("BLOCK_POLICY_FLIP_NOT_ALLOWED")
    if policy.get("allow_pyramiding") is not False:
        violations.append("BLOCK_POLICY_PYRAMIDING_NOT_ALLOWED")
    for key in ("test_capital_yen", "risk_per_trade_yen", "risk_per_trade_pct", "daily_stop_yen"):
        if not _is_positive_finite_number(policy.get(key)):
            violations.append("BLOCK_POLICY_INVALID_NUMERIC_VALUE")
            break
    max_open = policy.get("max_open_positions")
    if not _is_positive_finite_number(max_open) or int(max_open) != max_open:
        violations.append("BLOCK_POLICY_INVALID_MAX_OPEN_POSITIONS")
    return violations


def _block(base: dict, reasons: list[str]) -> dict:
    return {**base, "decision": "BLOCK", "allowed_qty": 0, "block_reasons": reasons}


def evaluate_risk(scenario: dict, *, available_cash_yen, open_positions_count,
                   realized_pnl_today_yen, regime_risk_multiplier,
                   estimated_fees_buffer_yen, lot_size, policy: dict) -> dict:
    """Position Sizing / Risk Gateの中核となる純粋関数。同一入力からは常に
    同一のRiskDecisionを返す（generated_atはwall-clockの記録用メタデータで
    あり、判定ロジックには一切使わない）。

    scenario: scripts/conflict_resolver.resolve_conflicts()が返す
        ResolvedScenario形の辞書。少なくとも resolved_status/symbol/side/
        horizon/merge_hash/entry/stop を持つことを期待する。原則
        resolved_status=="CANDIDATE_READY"のみを新規Sizing対象にする。
    available_cash_yen / open_positions_count / realized_pnl_today_yen /
        regime_risk_multiplier / estimated_fees_buffer_yen / lot_size:
        呼び出し側が別途集計して渡す口座/商品/regimeスナップショット値
        （このファイルはbroker/Excel/RSSへ取りに行かない）。
    policy: load_policy()が返す辞書。
    """
    generated_at = now_jst().isoformat()
    base = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": policy.get("policy_version"),
        "generated_at": generated_at,
        "symbol": scenario.get("symbol"),
        "side": scenario.get("side"),
        "horizon": scenario.get("horizon"),
        # canonical intent_hashではない。Conflict Resolverのmerge_hashを
        # 上流scenarioのlineage keyとしてそのまま保持するだけ。
        "merge_hash": scenario.get("merge_hash"),
        "decision": None,
        "allowed_qty": 0,
        "risk_budget_yen": None,
        "effective_risk_budget_yen": None,
        "stop_distance_yen": None,
        "block_reasons": [],
    }

    # --- BLOCK: policy自体の安全境界検証（Blocker 2、最優先） --------------
    policy_violations = validate_policy_v0_1(policy)
    if policy_violations:
        return _block(base, policy_violations)

    # --- BLOCK: 上流scenarioの状態検証 -----------------------------------
    if scenario.get("resolved_status") != "CANDIDATE_READY":
        return _block(base, ["RESOLVED_STATUS_NOT_CANDIDATE_READY"])

    symbol = scenario.get("symbol")
    if not symbol or not isinstance(symbol, str):
        return _block(base, ["BLOCK_SYMBOL_INVALID"])

    merge_hash = scenario.get("merge_hash")
    if not merge_hash or not isinstance(merge_hash, str):
        return _block(base, ["BLOCK_MERGE_HASH_INVALID"])

    horizon = scenario.get("horizon")
    if not horizon or not isinstance(horizon, str):
        return _block(base, ["HORIZON_MISSING"])

    side = scenario.get("side")
    if side not in VALID_SIDES:
        return _block(base, ["SIDE_INVALID"])

    entry = scenario.get("entry")
    stop = scenario.get("stop")
    if not _is_finite_number(entry) or entry <= 0:
        return _block(base, ["ENTRY_INVALID"])
    if not _is_finite_number(stop) or stop <= 0:
        return _block(base, ["STOP_INVALID"])

    # abs()だけでは逆方向stopを見逃す。BUYはstop<entry、SELLはstop>entryを
    # 必須にする（entry==stopもこの不等号を満たさないため自動的にBLOCK）。
    if side == "BUY" and not (stop < entry):
        return _block(base, ["BLOCK_INVALID_STOP_DIRECTION"])
    if side == "SELL" and not (stop > entry):
        return _block(base, ["BLOCK_INVALID_STOP_DIRECTION"])

    if not _is_finite_number(lot_size) or lot_size <= 0 or int(lot_size) != lot_size:
        return _block(base, ["LOT_SIZE_INVALID"])
    lot_size = int(lot_size)

    # Blocker 3: 非数値/NaN/infに加えて負値も拒否する。
    if not _is_finite_number(available_cash_yen) or available_cash_yen < 0:
        return _block(base, ["BLOCK_AVAILABLE_CASH_INVALID"])
    if not _is_finite_number(realized_pnl_today_yen):
        return _block(base, ["REALIZED_PNL_INVALID"])
    if not _is_finite_number(regime_risk_multiplier) or regime_risk_multiplier < 0:
        return _block(base, ["REGIME_MULTIPLIER_INVALID"])
    if not _is_finite_number(estimated_fees_buffer_yen) or estimated_fees_buffer_yen < 0:
        return _block(base, ["FEES_BUFFER_INVALID"])
    # Blocker 3: 0以上の"整数"であることを要求する（0.5等の小数を拒否）。
    if (not _is_finite_number(open_positions_count) or open_positions_count < 0
            or int(open_positions_count) != open_positions_count):
        return _block(base, ["OPEN_POSITIONS_COUNT_INVALID"])

    stop_distance_yen = abs(entry - stop)
    base["stop_distance_yen"] = stop_distance_yen

    # --- SHADOW_ONLY: sizing計算を要さない口座レベルのハードゲート ----------
    hard_shadow_reasons = []
    if policy.get("account_mode") == "CASH" and side == "SELL":
        hard_shadow_reasons.append("CASH_MODE_NO_SHORT")
    if open_positions_count >= policy["max_open_positions"]:
        hard_shadow_reasons.append("MAX_OPEN_POSITIONS_REACHED")
    daily_loss_used = max(0.0, -realized_pnl_today_yen)
    remaining_daily_loss_budget = policy["daily_stop_yen"] - daily_loss_used
    if remaining_daily_loss_budget <= 0:
        hard_shadow_reasons.append("DAILY_STOP_REACHED")
    if hard_shadow_reasons:
        return {**base, "decision": "SHADOW_ONLY", "allowed_qty": 0, "block_reasons": hard_shadow_reasons}

    # --- Sizing -----------------------------------------------------------
    base_risk_budget = min(policy["risk_per_trade_yen"],
                            policy["test_capital_yen"] * policy["risk_per_trade_pct"])
    # regime倍率は縮小側にのみ使う。>1.0でも1.0へcapし、budgetを拡大しない。
    regime_multiplier_effective = min(1.0, regime_risk_multiplier)
    risk_budget_yen = base_risk_budget * regime_multiplier_effective
    effective_risk_budget = min(risk_budget_yen, max(0.0, remaining_daily_loss_budget))
    base["risk_budget_yen"] = risk_budget_yen
    base["effective_risk_budget_yen"] = effective_risk_budget

    risk_per_lot_yen = stop_distance_yen * lot_size
    max_lots_by_risk = math.floor(effective_risk_budget / risk_per_lot_yen) if risk_per_lot_yen > 0 else 0

    # Blocker 1: 投下可能現金はtest_capital_yen（30万円）を上限にcapする。
    # available_cash_yenだけで計算すると、実口座余力が30万円を超えている場合に
    # 30万円テスト資金の枠を超える建玉がPASSしうる。
    cash_budget_yen = min(available_cash_yen, policy["test_capital_yen"])
    investable_cash_yen = max(0.0, cash_budget_yen - estimated_fees_buffer_yen)
    max_lots_by_cash = math.floor(investable_cash_yen / (entry * lot_size))

    allowed_lots = min(max_lots_by_risk, max_lots_by_cash)

    if allowed_lots <= 0:
        reason = "RISK_BUDGET_EXCEEDED" if max_lots_by_risk <= max_lots_by_cash else "INSUFFICIENT_CASH"
        return {**base, "decision": "SHADOW_ONLY", "allowed_qty": 0, "block_reasons": [reason]}

    return {**base, "decision": "PASS", "allowed_qty": allowed_lots * lot_size, "block_reasons": []}
