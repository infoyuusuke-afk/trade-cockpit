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

## Phase 3.2 hardening（1 blocker、C-051R-GPT）
Phase 3.1の`validate_policy_v0_1()`は「正の有限値であるか」しか見ておらず、
v0.1で凍結したはずの安全上限（30万円/750円/0.25%/3,000円/ポジション数1）
そのものは検証していなかった。設定ファイルが誤ってtest_capital_yen=
3,000,000等に書き換わっても、桁が正の数でありさえすればPASSしてしまう穴が
あった。修正：
1. `policy_version`が`"risk-gate-0.1.0"`と完全一致しない場合はBLOCK
   （`BLOCK_POLICY_VERSION_UNSUPPORTED`）。
2. test_capital_yen/risk_per_trade_yen/risk_per_trade_pct/daily_stop_yen
   がv0.1の上限（それぞれ300000/750/0.0025/3000）を超えていたらBLOCK。
   安全側への縮小（例: test_capital_yen=200000）はPASS対象として許可する。
3. max_open_positionsはv0.1では1固定。1以外は全てBLOCK
   （`BLOCK_POLICY_MAX_OPEN_POSITIONS_OUT_OF_RANGE`）。
4. `validate_policy_v0_1()`の入口でpolicyがdictかどうかを最初に検証し、
   None/list/文字列等ではその場で`BLOCK_POLICY_INVALID_TYPE`を返す
   （`.get()`を一切呼ばない）。呼び出し側のevaluate_risk()でもbase辞書の
   組み立てより前にこの検証を行うよう順序を修正し、非dict policyでも
   例外を出さずBLOCKを返せるようにした。
将来v0.1の上限を緩める場合は、この検証関数の定数を書き換えるのではなく
policy_versionを上げて新しいv0.2検証を別途実装する。

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
SCHEMA_VERSION = "risk-gate-1.2"
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


def _in_range_0_exclusive_to(value, upper_inclusive) -> bool:
    return _is_finite_number(value) and 0 < value <= upper_inclusive


# v0.1で凍結した安全上限そのもの（Issue #18 C-051R-GPT Phase 3.2）。ここに書いた
# 数値を緩める変更は、このコメントを含むコードレビューを経ずに行わない前提とする。
# 将来2ポジション以上・より広いrisk予算を許可する場合は、この定数を書き換えるのでは
# なくpolicy_versionを上げて新しいv0.2の検証関数を別途実装する。
POLICY_VERSION_V0_1 = "risk-gate-0.1.0"
V0_1_MAX_TEST_CAPITAL_YEN = 300000
V0_1_MAX_RISK_PER_TRADE_YEN = 750
V0_1_MAX_RISK_PER_TRADE_PCT = 0.0025
V0_1_MAX_DAILY_STOP_YEN = 3000
V0_1_MAX_OPEN_POSITIONS = 1


def validate_policy_v0_1(policy) -> list[str]:
    """v0.1 policyが安全境界の前提を満たしているか検証する純粋関数。

    2段階で守る（C-051R-GPT Phase 3.2）:
    1. 型そのものがdictでなければ（None/list/文字列等）、.get()を一切呼ばず
       即座にBLOCK_POLICY_INVALID_TYPEを返す——ここで例外を出さないことが
       呼び出し側（evaluate_risk）がpolicy.get()へ触れる前に安全側へ倒れる
       前提になる。
    2. dictであっても、policy_versionが"risk-gate-0.1.0"と完全一致しない場合
       や、各数値がv0.1で凍結した上限（30万円/750円/0.25%/3,000円/
       ポジション数1）を超えている場合はBLOCKにする。安全側への縮小
       （例: test_capital_yen=200000）はPASS対象として許可する——縮小と
       拡大を区別するのが本Phaseの目的であり、単なる「正の数であるか」
       だけのチェックでは設定変更だけでv0.1の安全境界を拡大できてしまう
       （C-051R-GPTが実例で指摘した穴）。

    キー欠損はKeyErrorを送出せず`.get()`で拾い、違反として報告する。
    違反が無ければ空リストを返す。
    """
    if not isinstance(policy, dict):
        return ["BLOCK_POLICY_INVALID_TYPE"]

    violations = []
    if policy.get("policy_version") != POLICY_VERSION_V0_1:
        violations.append("BLOCK_POLICY_VERSION_UNSUPPORTED")
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

    if not _in_range_0_exclusive_to(policy.get("test_capital_yen"), V0_1_MAX_TEST_CAPITAL_YEN):
        violations.append("BLOCK_POLICY_TEST_CAPITAL_OUT_OF_RANGE")
    if not _in_range_0_exclusive_to(policy.get("risk_per_trade_yen"), V0_1_MAX_RISK_PER_TRADE_YEN):
        violations.append("BLOCK_POLICY_RISK_PER_TRADE_YEN_OUT_OF_RANGE")
    if not _in_range_0_exclusive_to(policy.get("risk_per_trade_pct"), V0_1_MAX_RISK_PER_TRADE_PCT):
        violations.append("BLOCK_POLICY_RISK_PER_TRADE_PCT_OUT_OF_RANGE")
    if not _in_range_0_exclusive_to(policy.get("daily_stop_yen"), V0_1_MAX_DAILY_STOP_YEN):
        violations.append("BLOCK_POLICY_DAILY_STOP_OUT_OF_RANGE")

    max_open = policy.get("max_open_positions")
    if not (_is_positive_finite_number(max_open) and int(max_open) == max_open
            and max_open == V0_1_MAX_OPEN_POSITIONS):
        violations.append("BLOCK_POLICY_MAX_OPEN_POSITIONS_OUT_OF_RANGE")

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

    # policy自体の安全境界検証を最優先・最初に行う（C-051R-GPT Phase 3.2）。
    # policyがNone/list/文字列等の非dictでも、base辞書組み立て（旧実装は
    # policy.get(...)を先に呼んでいたため非dictで例外になっていた）より前に
    # validate_policy_v0_1()内で型チェックだけを行い、.get()には一切触れずに
    # 判定するため、ここでは例外が発生しない。
    policy_violations = validate_policy_v0_1(policy)
    safe_policy_version = policy.get("policy_version") if isinstance(policy, dict) else None

    base = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": safe_policy_version,
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
