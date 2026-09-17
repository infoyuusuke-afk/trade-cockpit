"""scripts/shadow_position.py

Shadow Position Lifecycle + Protective Exit Model v0.1（GitHub Issue #18
Execution Stack Phase 5.1、C-065-GPT comment 5709773735 対応）。

100% Shadow。Real broker/RSS/Excelへの副作用は一切ない。検証済みの正の
entry fillを1つのdeterministic Shadow Positionへ変換し、point-in-time
`MarketObservation`からprotective stop・1本のplanned targetを保守的に
モデル化する純粋関数群。

## canonical入力とlineage
Positionは以下からのみ作る：
1. canonical Intent（execution_contract.build_intent()産出物）
2. `filled_qty>0`かつstatusが`PARTIAL_FILLED`または`FILLED`の
   Phase 5.0.x full-schema Shadow Order（shadow_execution.py産出物）
3. 明示的なtimezone-aware `now`

stop/targetを市場データやstrategy defaultから再構成しない。
`intent_hash`を`execution_contract.compute_intent_hash()`で再計算・
照合し、Shadow Orderの`intent_hash`/`merge_hash`/`symbol`/`side`/
`requested_qty`/`shadow_order_id`がIntent/order lineageと一致することを
要求する。Shadow Order自体のstate-integrity検証は
`shadow_execution.validate_shadow_order_state()`を再利用し、ここで弱い
独自コピーを作らない。

`planned_target`はcanonical `_HASH_FIELDS`に含まれない——`intent_hash`が
一致してもmutableな`Intent.planned_target`を信頼してはならない。新設の
`position_plan_fingerprint`が`position_id`/`shadow_order_id`/
`order_context_fingerprint`/`intent_hash`/`merge_hash`/
`ticket_fingerprint`/`symbol`/`side`/`planned_entry`/`planned_stop`/
`planned_target`/`strategy_id`/`strategy_version`/`risk_policy_version`/
`position_opened_at`を束縛する。canonical `intent_hash`のsemanticsは
これで変更しない。

## position identity / state
`position_id = sha256(shadow_order_id + "|shadow-position-0.1")`
（ランダムUUIDは使わない）。state: `OPEN`/`STOP_TRIGGERED`/
`STOP_EXIT_PARTIAL`/`CLOSED`（+ 壊れたinputをfail-closedする
`REJECTED`）。1つのShadow Order→1つのPosition。同一shadow_order_idの
positionは二重生成しない（`DUPLICATE_IGNORED`）。
`position_opened_at = shadow_order.first_fill_at`（最終fill時刻では
ない）。

## partial entry fill同期
`PARTIAL_FILLED`のentryは既にOPEN Positionを作る——protective riskは
最初の正のfillから起算する。OPEN中は同一Shadow Orderの新しいstateで
entry数量を増やせるが、減少/巻き戻し・identity変更は許さない。
Shadow Orderの累積`avg_fill_price`をそのまま信頼する（推測で再計算
しない）。`STOP_TRIGGERED`/`STOP_EXIT_PARTIAL`/`CLOSED`へ進んだ後は、
以後のentry fill増加を一切受け付けない（`entry_sync_reasons`で理由を
明示して無視する）。

## protective stop semantics（保守的 v0.1）
BUY: `last_trade_price<=planned_stop`、SELL: `last_trade_price>=
planned_stop`でtrigger。**trigger観測と同じobservationではfillしない**
——`status=STOP_TRIGGERED`・`stop_triggered_at`を記録し、exit数量ゼロの
まま次の厳密に新しいobservationを待つ。以後の観測は
`shadow_fill_model.evaluate_market_fill()`をそのまま再利用した
MARKET exit（long exit SELLはbid/bid_qty、short exit BUYはask/ask_qty）
として評価する——`submitted_at=stop_triggered_at`を渡すことで
「trigger観測と同じobservationでは使わない」制約をFill Model自身の
既存gateにそのまま委譲する。可視数量不足はpartial exitのみ
（`STOP_EXIT_PARTIAL`）。gapは実際に観測されたadverse BBOを使う
（Fill Modelがask/bidを参照する設計のため自動的に満たされる）。

## planned target semantics（limit-style、v0.1は1本のみ）
`planned_target=None`は有効（stop-onlyポジション）。方向が逆なら
position作成時にREJECTEDにする。OPENなpositionに対し、targetは
`shadow_fill_model.evaluate_limit_fill()`をそのまま反対側のLIMIT exit
として再利用する（`submitted_at=position_opened_at`）——trade-throughは
CERTAIN fullクローズ、touch-onlyはUNCERTAINで確定closeにしない。STOP
trigger後はtargetロジックを無効化する。

## position chronology / observation watermark
Shadow Order本体とは別のposition観測watermark
（`first_position_observation_at`/`last_position_observation_at`）を
保持し、duplicate/out-of-order observationがexitを二重fillできない
ようにする。entry fill更新とexit observationが同一/巻き戻り
timestampの場合は順序を捏造せずexitを拒否する
（`AMBIGUOUS_ENTRY_EXIT_ORDERING`）。

## real_submit_allowedについて
このモジュールが返すどの辞書も`real_submit_allowed`は常にFalse固定。
RssOrder・Excel注文式・broker submit・実ポジション変更は一切実装しない。
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import execution_contract as ec
import shadow_execution as se
import shadow_fill_model as sfm

SCHEMA_VERSION = "shadow-position-0.1"

POSITION_STATUSES = ("OPEN", "STOP_TRIGGERED", "STOP_EXIT_PARTIAL", "CLOSED", "REJECTED", "DUPLICATE_IGNORED")

# CLOSED/REJECTED/DUPLICATE_IGNOREDからは一切再評価しない（自動retryを表現しない）。
# DUPLICATE_IGNOREDはcreate_shadow_position()の早期パスが返す最小フィールドの
# 辞書なのでstate-integrity検証の対象から明示的に除外する。
_MINIMAL_TERMINAL_STATUSES = frozenset({"REJECTED", "DUPLICATE_IGNORED"})
_FULL_TERMINAL_STATUSES = frozenset({"CLOSED"})
_TERMINAL_STATUSES = _MINIMAL_TERMINAL_STATUSES | _FULL_TERMINAL_STATUSES

_OPEN_LIKE_STATUSES = frozenset({"OPEN", "STOP_TRIGGERED", "STOP_EXIT_PARTIAL"})


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_finite_positive(value) -> bool:
    return _is_finite_number(value) and value > 0


def _is_aware_datetime(value) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None


def compute_position_id(shadow_order_id: str) -> str:
    """`sha256(shadow_order_id + "|shadow-position-0.1")`による決定論的ID
    （ランダムUUIDは使わない、Golden #21）。"""
    payload = f"{shadow_order_id}|shadow-position-0.1".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_position_plan_fingerprint(*, position_id, shadow_order_id, order_context_fingerprint,
                                       intent_hash, merge_hash, ticket_fingerprint, symbol, side,
                                       planned_entry, planned_stop, planned_target, strategy_id,
                                       strategy_version, risk_policy_version, position_opened_at) -> str:
    """canonical `intent_hash`は`planned_target`を含まないため（Phase 1の
    `_HASH_FIELDS`）、intent_hash一致だけではmutableな`Intent.
    planned_target`を信頼できない。この決定論的fingerprintが
    position生成時のplanned_entry/stop/target等をbindし、以後の評価
    直前に再計算・照合する（Golden #7）。"""
    payload = {
        "position_id": position_id,
        "shadow_order_id": shadow_order_id,
        "order_context_fingerprint": order_context_fingerprint,
        "intent_hash": intent_hash,
        "merge_hash": merge_hash,
        "ticket_fingerprint": ticket_fingerprint,
        "symbol": symbol,
        "side": side,
        "planned_entry": float(planned_entry) if _is_finite_number(planned_entry) else None,
        "planned_stop": float(planned_stop) if _is_finite_number(planned_stop) else None,
        "planned_target": float(planned_target) if _is_finite_number(planned_target) else None,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "risk_policy_version": risk_policy_version,
        "position_opened_at": position_opened_at.isoformat() if isinstance(position_opened_at, datetime) else None,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rejected_position(reasons, *, shadow_order_id=None, intent_hash=None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "position_id": None,
        "shadow_order_id": shadow_order_id,
        "intent_hash": intent_hash,
        "status": "REJECTED",
        "reject_reasons": sorted(set(reasons)),
        "real_submit_allowed": False,
    }


def create_shadow_position(intent: dict, shadow_order: dict, *, now: datetime,
                            known_positions: list[dict]) -> dict:
    """Shadow Orderの正のentry fillから1件のShadow Positionを生成する
    純粋関数。lineageが不正・Shadow Order自体がfail-closedならREJECTED、
    同一shadow_order_idのpositionが既に`known_positions`に存在すれば
    `DUPLICATE_IGNORED`を返す（Golden #1/#4/#5/#6/#8）。

    `known_positions`: 既知positionレコードのリスト（各要素は最低
    `position_id`を持つ辞書）。永続化はこの関数の外の責務。
    """
    intent_hash_in = intent.get("intent_hash") if isinstance(intent, dict) else None
    shadow_order_id_in = shadow_order.get("shadow_order_id") if isinstance(shadow_order, dict) else None

    reasons = []
    if not isinstance(intent, dict):
        reasons.append("REJECTED_INTENT_INVALID_TYPE")
    if not isinstance(shadow_order, dict):
        reasons.append("REJECTED_SHADOW_ORDER_INVALID_TYPE")
    if reasons:
        return _rejected_position(reasons, shadow_order_id=shadow_order_id_in, intent_hash=intent_hash_in)

    # 1. canonical intent_hashの再計算・改ざん検証（再定義はしない）。
    try:
        recomputed_intent_hash = ec.compute_intent_hash(intent)
    except Exception:  # noqa: BLE001 - 壊れたIntentは安全側でREJECTED
        reasons.append("REJECTED_INTENT_MALFORMED")
    else:
        if intent.get("intent_hash") != recomputed_intent_hash:
            reasons.append("REJECTED_INTENT_HASH_TAMPERED")

    if intent.get("real_submit_allowed") is not False:
        reasons.append("REJECTED_REAL_SUBMIT_ALLOWED_NOT_FALSE")

    # 2. Shadow Order自体がPosition入力として使える形か（Golden #1）。
    status = shadow_order.get("status")
    if status not in ("PARTIAL_FILLED", "FILLED"):
        reasons.append("REJECTED_SHADOW_ORDER_NOT_POSITIVE_FILL")
    filled_qty = shadow_order.get("filled_qty")
    if not (_is_finite_number(filled_qty) and filled_qty > 0):
        reasons.append("REJECTED_SHADOW_ORDER_NOT_POSITIVE_FILL")

    # Shadow Order自体のstate-integrityはshadow_execution.py側のcanonical
    # 検証をそのまま再利用する（弱い独自コピーを作らない）。
    reasons.extend(se.validate_shadow_order_state(shadow_order, now=now))

    # 3. Intent <-> Shadow Order lineageの一致確認。
    if intent.get("intent_hash") != shadow_order.get("intent_hash"):
        reasons.append("REJECTED_LINEAGE_INTENT_HASH_MISMATCH")
    if intent.get("merge_hash") != shadow_order.get("merge_hash"):
        reasons.append("REJECTED_LINEAGE_MERGE_HASH_MISMATCH")
    if intent.get("symbol") != shadow_order.get("symbol"):
        reasons.append("REJECTED_LINEAGE_SYMBOL_MISMATCH")
    if intent.get("side") != shadow_order.get("side"):
        reasons.append("REJECTED_LINEAGE_SIDE_MISMATCH")
    if intent.get("quantity") != shadow_order.get("requested_qty"):
        reasons.append("REJECTED_LINEAGE_REQUESTED_QTY_MISMATCH")
    expected_shadow_order_id = se.compute_shadow_order_id(
        intent.get("intent_hash"), intent.get("shadow_fill_model_version"))
    if shadow_order.get("shadow_order_id") != expected_shadow_order_id:
        reasons.append("REJECTED_LINEAGE_SHADOW_ORDER_ID_MISMATCH")

    ticket_fingerprint = shadow_order.get("ticket_fingerprint")
    if not ticket_fingerprint or not isinstance(ticket_fingerprint, str):
        reasons.append("REJECTED_TICKET_FINGERPRINT_MISSING")

    order_context_fingerprint = shadow_order.get("order_context_fingerprint")
    if not order_context_fingerprint or not isinstance(order_context_fingerprint, str):
        reasons.append("REJECTED_ORDER_CONTEXT_FINGERPRINT_MISSING")

    # 4. planned_stop/planned_targetの方向検証（Golden #8）。
    side = intent.get("side")
    planned_entry = intent.get("planned_entry")
    planned_stop = intent.get("planned_stop")
    planned_target = intent.get("planned_target")
    if side in ec.VALID_SIDES and _is_finite_number(planned_entry) and _is_finite_number(planned_stop):
        if side == "BUY" and not (planned_stop < planned_entry):
            reasons.append("REJECTED_PLANNED_STOP_WRONG_DIRECTION")
        if side == "SELL" and not (planned_stop > planned_entry):
            reasons.append("REJECTED_PLANNED_STOP_WRONG_DIRECTION")
    else:
        reasons.append("REJECTED_PLANNED_STOP_INVALID")

    if planned_target is not None:
        if side in ec.VALID_SIDES and _is_finite_number(planned_entry) and _is_finite_number(planned_target):
            if side == "BUY" and not (planned_target > planned_entry):
                reasons.append("REJECTED_PLANNED_TARGET_WRONG_DIRECTION")
            if side == "SELL" and not (planned_target < planned_entry):
                reasons.append("REJECTED_PLANNED_TARGET_WRONG_DIRECTION")
        else:
            reasons.append("REJECTED_PLANNED_TARGET_INVALID")

    if reasons:
        return _rejected_position(reasons, shadow_order_id=shadow_order_id_in, intent_hash=intent_hash_in)

    if not isinstance(known_positions, list) or not all(isinstance(x, dict) for x in known_positions):
        return _rejected_position(["REJECTED_KNOWN_POSITIONS_INVALID"], shadow_order_id=shadow_order_id_in,
                                   intent_hash=intent_hash_in)

    position_id = compute_position_id(shadow_order["shadow_order_id"])
    for known in known_positions:
        if known.get("position_id") == position_id:
            return {
                "schema_version": SCHEMA_VERSION,
                "position_id": position_id,
                "shadow_order_id": shadow_order["shadow_order_id"],
                "status": "DUPLICATE_IGNORED",
                "reject_reasons": [],
                "real_submit_allowed": False,
            }

    position_opened_at = shadow_order.get("first_fill_at")
    entry_qty = int(filled_qty)
    avg_entry_price = shadow_order.get("avg_fill_price")
    last_entry_fill_at = shadow_order.get("last_fill_at")

    position_plan_fingerprint = compute_position_plan_fingerprint(
        position_id=position_id, shadow_order_id=shadow_order["shadow_order_id"],
        order_context_fingerprint=order_context_fingerprint, intent_hash=intent["intent_hash"],
        merge_hash=intent.get("merge_hash"), ticket_fingerprint=ticket_fingerprint,
        symbol=intent.get("symbol"), side=side, planned_entry=planned_entry, planned_stop=planned_stop,
        planned_target=planned_target, strategy_id=intent.get("strategy_id"),
        strategy_version=intent.get("strategy_version"), risk_policy_version=intent.get("risk_policy_version"),
        position_opened_at=position_opened_at,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "position_id": position_id,
        "shadow_order_id": shadow_order["shadow_order_id"],
        "order_context_fingerprint": order_context_fingerprint,
        "position_plan_fingerprint": position_plan_fingerprint,
        "intent_hash": intent["intent_hash"],
        "merge_hash": intent.get("merge_hash"),
        "ticket_fingerprint": ticket_fingerprint,
        "symbol": intent.get("symbol"),
        "side": side,
        "planned_entry": planned_entry,
        "planned_stop": planned_stop,
        "planned_target": planned_target,
        "strategy_id": intent.get("strategy_id"),
        "strategy_version": intent.get("strategy_version"),
        "risk_policy_version": intent.get("risk_policy_version"),
        "status": "OPEN",
        "entry_filled_qty_seen": entry_qty,
        "current_qty": entry_qty,
        "avg_entry_price": avg_entry_price,
        "position_opened_at": position_opened_at,
        "last_entry_fill_at": last_entry_fill_at,
        "first_position_observation_at": None,
        "last_position_observation_at": None,
        "stop_triggered_at": None,
        "first_stop_exit_fill_at": None,
        "last_stop_exit_fill_at": None,
        "exit_filled_qty": 0,
        "remaining_position_qty": entry_qty,
        "avg_exit_price": None,
        "exit_reason": None,
        "closed_at": None,
        "fill_confidence": None,
        "fill_reason": None,
        "best_bid": None, "best_ask": None, "bid_qty": None, "ask_qty": None,
        "spread_yen": None,
        "slippage_yen": None, "slippage_bps": None, "slippage_model_status": None,
        "ambiguity_flags": [],
        "entry_sync_reasons": [],
        "reject_reasons": [],
        "real_submit_allowed": False,
    }


def _validate_position_state(position: dict, *, now: datetime) -> list[str]:
    """永続化されたShadow Positionの不変条件をfail-closedで検証する
    純粋関数。違反があれば既存値を推測補正せず、理由コードのリストを
    返す（空なら健全）。例外は投げない。
    """
    reasons = []

    entry_seen = position.get("entry_filled_qty_seen")
    current_qty = position.get("current_qty")
    exit_filled = position.get("exit_filled_qty")
    remaining = position.get("remaining_position_qty")
    avg_entry_price = position.get("avg_entry_price")

    entry_ok = _is_finite_number(entry_seen) and int(entry_seen) == entry_seen and entry_seen > 0
    if not entry_ok:
        reasons.append("REJECTED_POSITION_ENTRY_QTY_INVALID")

    current_ok = _is_finite_number(current_qty) and int(current_qty) == current_qty and current_qty >= 0
    if not current_ok:
        reasons.append("REJECTED_POSITION_CURRENT_QTY_INVALID")

    exit_ok = _is_finite_number(exit_filled) and int(exit_filled) == exit_filled and exit_filled >= 0
    if not exit_ok:
        reasons.append("REJECTED_POSITION_EXIT_QTY_INVALID")

    if entry_ok and current_ok and exit_ok:
        if current_qty > entry_seen or current_qty != entry_seen - exit_filled:
            reasons.append("REJECTED_POSITION_QTY_INCONSISTENT")

    if current_ok and remaining != current_qty:
        reasons.append("REJECTED_POSITION_QTY_INCONSISTENT")

    if entry_ok and not (_is_finite_number(avg_entry_price) and avg_entry_price > 0):
        reasons.append("REJECTED_POSITION_AVG_ENTRY_PRICE_INVALID")

    if exit_ok and exit_filled > 0:
        avg_exit_price = position.get("avg_exit_price")
        if not (_is_finite_number(avg_exit_price) and avg_exit_price > 0):
            reasons.append("REJECTED_POSITION_AVG_EXIT_PRICE_INVALID")

    if position.get("real_submit_allowed") is not False:
        reasons.append("REJECTED_POSITION_REAL_SUBMIT_ALLOWED_NOT_FALSE")

    status = position.get("status")
    if status not in POSITION_STATUSES:
        reasons.append("REJECTED_POSITION_STATUS_INVALID")
    elif current_ok:
        if status == "CLOSED" and current_qty != 0:
            reasons.append("REJECTED_POSITION_STATUS_QUANTITY_MISMATCH")
        elif status in _OPEN_LIKE_STATUSES and current_qty <= 0:
            reasons.append("REJECTED_POSITION_STATUS_QUANTITY_MISMATCH")

    # position_id / position_plan_fingerprintの再照合（Golden #7）。
    expected_position_id = compute_position_id(position.get("shadow_order_id"))
    if position.get("position_id") != expected_position_id:
        reasons.append("REJECTED_POSITION_ID_MISMATCH")

    position_opened_at = position.get("position_opened_at")
    expected_plan_fp = compute_position_plan_fingerprint(
        position_id=position.get("position_id"), shadow_order_id=position.get("shadow_order_id"),
        order_context_fingerprint=position.get("order_context_fingerprint"),
        intent_hash=position.get("intent_hash"), merge_hash=position.get("merge_hash"),
        ticket_fingerprint=position.get("ticket_fingerprint"), symbol=position.get("symbol"),
        side=position.get("side"), planned_entry=position.get("planned_entry"),
        planned_stop=position.get("planned_stop"), planned_target=position.get("planned_target"),
        strategy_id=position.get("strategy_id"), strategy_version=position.get("strategy_version"),
        risk_policy_version=position.get("risk_policy_version"), position_opened_at=position_opened_at,
    )
    if position.get("position_plan_fingerprint") != expected_plan_fp:
        reasons.append("REJECTED_POSITION_PLAN_MISMATCH")

    # --- chronology（section 6） ------------------------------------------
    now_ok = _is_aware_datetime(now)
    if not now_ok:
        reasons.append("REJECTED_POSITION_NOW_INVALID")

    opened_ok = _is_aware_datetime(position_opened_at)
    if not opened_ok:
        reasons.append("REJECTED_POSITION_OPENED_AT_INVALID")
    elif now_ok and position_opened_at > now:
        reasons.append("REJECTED_POSITION_OPENED_AT_INVALID")
        opened_ok = False

    last_entry_fill_at = position.get("last_entry_fill_at")
    last_entry_ok = _is_aware_datetime(last_entry_fill_at)
    if not last_entry_ok:
        reasons.append("REJECTED_POSITION_LAST_ENTRY_FILL_AT_INVALID")
    else:
        if opened_ok and last_entry_fill_at < position_opened_at:
            reasons.append("REJECTED_POSITION_LAST_ENTRY_FILL_AT_INVALID")
            last_entry_ok = False
        if now_ok and last_entry_fill_at > now:
            reasons.append("REJECTED_POSITION_LAST_ENTRY_FILL_AT_INVALID")
            last_entry_ok = False

    first_pos_obs = position.get("first_position_observation_at")
    last_pos_obs = position.get("last_position_observation_at")
    if (first_pos_obs is not None) != (last_pos_obs is not None):
        if first_pos_obs is None:
            reasons.append("REJECTED_POSITION_FIRST_OBSERVATION_AT_INVALID")
        if last_pos_obs is None:
            reasons.append("REJECTED_POSITION_LAST_OBSERVATION_AT_INVALID")
    first_pos_obs_ok = False
    if first_pos_obs is not None:
        if not _is_aware_datetime(first_pos_obs):
            reasons.append("REJECTED_POSITION_FIRST_OBSERVATION_AT_INVALID")
        else:
            first_pos_obs_ok = True
            if opened_ok and first_pos_obs <= position_opened_at:
                reasons.append("REJECTED_POSITION_FIRST_OBSERVATION_AT_INVALID")
                first_pos_obs_ok = False
            if now_ok and first_pos_obs > now:
                reasons.append("REJECTED_POSITION_FIRST_OBSERVATION_AT_INVALID")
                first_pos_obs_ok = False
    if last_pos_obs is not None:
        if not _is_aware_datetime(last_pos_obs):
            reasons.append("REJECTED_POSITION_LAST_OBSERVATION_AT_INVALID")
        else:
            if first_pos_obs_ok and last_pos_obs < first_pos_obs:
                reasons.append("REJECTED_POSITION_LAST_OBSERVATION_AT_INVALID")
            if now_ok and last_pos_obs > now:
                reasons.append("REJECTED_POSITION_LAST_OBSERVATION_AT_INVALID")

    stop_triggered_at = position.get("stop_triggered_at")
    stop_triggered_ok = False
    if stop_triggered_at is not None:
        if status == "OPEN":
            reasons.append("REJECTED_POSITION_STOP_TRIGGERED_AT_INVALID")
        if not _is_aware_datetime(stop_triggered_at):
            reasons.append("REJECTED_POSITION_STOP_TRIGGERED_AT_INVALID")
        else:
            stop_triggered_ok = True
            if opened_ok and stop_triggered_at <= position_opened_at:
                reasons.append("REJECTED_POSITION_STOP_TRIGGERED_AT_INVALID")
                stop_triggered_ok = False
            if now_ok and stop_triggered_at > now:
                reasons.append("REJECTED_POSITION_STOP_TRIGGERED_AT_INVALID")
                stop_triggered_ok = False
    elif status in ("STOP_TRIGGERED", "STOP_EXIT_PARTIAL"):
        reasons.append("REJECTED_POSITION_STOP_TRIGGERED_AT_INVALID")
    elif status == "CLOSED" and position.get("exit_reason") == "STOP":
        reasons.append("REJECTED_POSITION_STOP_TRIGGERED_AT_INVALID")

    first_stop_exit_fill_at = position.get("first_stop_exit_fill_at")
    last_stop_exit_fill_at = position.get("last_stop_exit_fill_at")
    if exit_ok and exit_filled == 0:
        if first_stop_exit_fill_at is not None or last_stop_exit_fill_at is not None:
            reasons.append("REJECTED_POSITION_STOP_EXIT_FILL_AT_INVALID")
    elif exit_ok and exit_filled > 0:
        first_exit_ok = _is_aware_datetime(first_stop_exit_fill_at)
        last_exit_ok = _is_aware_datetime(last_stop_exit_fill_at)
        if not first_exit_ok:
            reasons.append("REJECTED_POSITION_STOP_EXIT_FILL_AT_INVALID")
        if not last_exit_ok:
            reasons.append("REJECTED_POSITION_STOP_EXIT_FILL_AT_INVALID")
        if first_exit_ok:
            if stop_triggered_ok and first_stop_exit_fill_at <= stop_triggered_at:
                reasons.append("REJECTED_POSITION_STOP_EXIT_FILL_AT_INVALID")
                first_exit_ok = False
        if last_exit_ok:
            if now_ok and last_stop_exit_fill_at > now:
                reasons.append("REJECTED_POSITION_STOP_EXIT_FILL_AT_INVALID")
                last_exit_ok = False
        if first_exit_ok and last_exit_ok and first_stop_exit_fill_at > last_stop_exit_fill_at:
            reasons.append("REJECTED_POSITION_STOP_EXIT_FILL_AT_INVALID")

    if status == "CLOSED":
        closed_at = position.get("closed_at")
        if not _is_aware_datetime(closed_at):
            reasons.append("REJECTED_POSITION_CLOSED_AT_INVALID")
        elif now_ok and closed_at > now:
            reasons.append("REJECTED_POSITION_CLOSED_AT_INVALID")
        if position.get("exit_reason") not in ("STOP", "TARGET"):
            reasons.append("REJECTED_POSITION_EXIT_REASON_INVALID")

    return reasons


def sync_entry_fill(position: dict, shadow_order: dict, *, now: datetime) -> dict:
    """同一Shadow Orderの新しいstateからentry数量/平均単価を同期する
    純粋関数。OPEN以外（STOP_TRIGGERED/STOP_EXIT_PARTIAL/CLOSED/
    REJECTED/DUPLICATE_IGNORED）では一切増加を反映せず、理由を
    `entry_sync_reasons`に明示する（Golden #17）。数量の減少/巻き戻し・
    identity不一致はfail-closedする（Golden #4）。
    """
    if not isinstance(position, dict):
        raise ValueError("position must be a dict")

    status = position.get("status")
    if status in _TERMINAL_STATUSES:
        return dict(position)

    state_reasons = _validate_position_state(position, now=now)
    if state_reasons:
        return {
            **position, "status": "REJECTED",
            "reject_reasons": sorted(set(position.get("reject_reasons") or []) | set(state_reasons)),
            "real_submit_allowed": False,
        }

    if status != "OPEN":
        return {**position, "entry_sync_reasons": ["BLOCKED_POSITION_NOT_OPEN"], "real_submit_allowed": False}

    if not isinstance(shadow_order, dict):
        return {**position, "entry_sync_reasons": ["REJECTED_SHADOW_ORDER_INVALID_TYPE"],
                "real_submit_allowed": False}

    if shadow_order.get("shadow_order_id") != position.get("shadow_order_id"):
        return {**position, "entry_sync_reasons": ["REJECTED_SHADOW_ORDER_IDENTITY_MISMATCH"],
                "real_submit_allowed": False}

    order_state_reasons = se.validate_shadow_order_state(shadow_order, now=now)
    if order_state_reasons:
        return {**position, "entry_sync_reasons": sorted(set(order_state_reasons)), "real_submit_allowed": False}

    new_filled = shadow_order.get("filled_qty")
    entry_seen = position.get("entry_filled_qty_seen")

    if not (_is_finite_number(new_filled) and int(new_filled) == new_filled and new_filled >= 0):
        return {**position, "entry_sync_reasons": ["REJECTED_SHADOW_ORDER_FILLED_QTY_INVALID"],
                "real_submit_allowed": False}

    if new_filled < entry_seen:
        return {**position, "entry_sync_reasons": ["REJECTED_ENTRY_QTY_ROLLBACK"], "real_submit_allowed": False}

    if new_filled == entry_seen:
        return {**position, "entry_sync_reasons": [], "real_submit_allowed": False}

    new_avg_entry = shadow_order.get("avg_fill_price")
    if not (_is_finite_number(new_avg_entry) and new_avg_entry > 0):
        return {**position, "entry_sync_reasons": ["REJECTED_SHADOW_ORDER_AVG_FILL_PRICE_INVALID"],
                "real_submit_allowed": False}

    new_last_entry_fill_at = shadow_order.get("last_fill_at")
    if not _is_aware_datetime(new_last_entry_fill_at):
        return {**position, "entry_sync_reasons": ["REJECTED_SHADOW_ORDER_LAST_FILL_AT_INVALID"],
                "real_submit_allowed": False}

    return {
        **position,
        "entry_filled_qty_seen": int(new_filled),
        "current_qty": int(new_filled),
        "remaining_position_qty": int(new_filled),
        "avg_entry_price": new_avg_entry,
        "last_entry_fill_at": new_last_entry_fill_at,
        "entry_sync_reasons": [],
        "real_submit_allowed": False,
    }


def evaluate_position_exit(position: dict, observation: dict, *, now: datetime) -> dict:
    """1件のMarketObservationを適用してprotective stop / planned target
    を評価する純粋関数。terminal状態（CLOSED/REJECTED/DUPLICATE_IGNORED）
    からは一切再評価しない（Golden #19）。新しいdictを返し、引数の
    `position`自体は書き換えない。
    """
    if not isinstance(position, dict):
        raise ValueError("position must be a dict")

    status = position.get("status")
    if status in _MINIMAL_TERMINAL_STATUSES:
        return dict(position)

    state_reasons = _validate_position_state(position, now=now)
    if state_reasons:
        return {
            **position, "status": "REJECTED",
            "reject_reasons": sorted(set(position.get("reject_reasons") or []) | set(state_reasons)),
            "real_submit_allowed": False,
        }

    if status in _FULL_TERMINAL_STATUSES:
        return dict(position)

    side = position.get("side")
    exit_side = "SELL" if side == "BUY" else "BUY"
    current_qty = position.get("current_qty")
    position_opened_at = position.get("position_opened_at")
    last_entry_fill_at = position.get("last_entry_fill_at")
    planned_stop = position.get("planned_stop")
    planned_target = position.get("planned_target")

    observed_at = observation.get("observed_at") if isinstance(observation, dict) else None
    observed_at_valid = isinstance(observed_at, datetime) and observed_at.tzinfo is not None

    # Golden #18: entryとexitの同一/巻き戻りtimestampの順序を捏造しない。
    if observed_at_valid and observed_at <= last_entry_fill_at:
        return {**position, "fill_reason": "AMBIGUOUS_ENTRY_EXIT_ORDERING", "real_submit_allowed": False}

    # Golden #15: position-level watermarkでduplicate/out-of-orderを防ぐ。
    last_pos_obs = position.get("last_position_observation_at")
    if observed_at_valid and last_pos_obs is not None and observed_at <= last_pos_obs:
        reason = "DUPLICATE_POSITION_OBSERVATION" if observed_at == last_pos_obs else "OUT_OF_ORDER_POSITION_OBSERVATION"
        return {**position, "fill_reason": reason, "real_submit_allowed": False}

    new_first_pos_obs = position.get("first_position_observation_at")
    new_last_pos_obs = last_pos_obs
    if observed_at_valid:
        if new_first_pos_obs is None:
            new_first_pos_obs = observed_at
        if new_last_pos_obs is None or observed_at > new_last_pos_obs:
            new_last_pos_obs = observed_at

    if status == "OPEN":
        ok, _obs_reasons = sfm.validate_observation(observation, now=now)
        last_trade_price = observation.get("last_trade_price") if isinstance(observation, dict) else None
        stop_hit = False
        if ok and _is_finite_positive(last_trade_price):
            if side == "BUY" and last_trade_price <= planned_stop:
                stop_hit = True
            elif side == "SELL" and last_trade_price >= planned_stop:
                stop_hit = True

        if stop_hit:
            # Golden #11: trigger観測と同じobservationではfillしない。
            return {
                **position,
                "status": "STOP_TRIGGERED",
                "stop_triggered_at": observed_at,
                "fill_confidence": "CERTAIN",
                "fill_reason": "STOP_TRIGGERED",
                "first_position_observation_at": new_first_pos_obs,
                "last_position_observation_at": new_last_pos_obs,
                "real_submit_allowed": False,
            }

        if planned_target is not None:
            # Golden #9/#10: 既存のconservativeなLIMIT fill semanticsを
            # そのまま反対側exitとして再利用する。
            target_result = sfm.evaluate_limit_fill(
                side=exit_side, requested_qty=current_qty, limit_price=planned_target,
                observation=observation, now=now, submitted_at=position_opened_at,
            )
            if target_result["filled_qty"] > 0:
                return {
                    **position,
                    "status": "CLOSED",
                    "current_qty": 0,
                    "remaining_position_qty": 0,
                    "exit_filled_qty": current_qty,
                    "avg_exit_price": target_result["avg_fill_price"],
                    "exit_reason": "TARGET",
                    "closed_at": observed_at,
                    "fill_confidence": target_result["fill_confidence"],
                    "fill_reason": target_result["fill_reason"],
                    "best_bid": target_result["best_bid"], "best_ask": target_result["best_ask"],
                    "spread_yen": target_result["spread_yen"],
                    "slippage_yen": target_result["slippage_yen"],
                    "slippage_bps": target_result["slippage_bps"],
                    "slippage_model_status": target_result["slippage_model_status"],
                    "first_position_observation_at": new_first_pos_obs,
                    "last_position_observation_at": new_last_pos_obs,
                    "real_submit_allowed": False,
                }
            return {
                **position,
                "fill_confidence": target_result["fill_confidence"],
                "fill_reason": target_result["fill_reason"],
                "first_position_observation_at": new_first_pos_obs,
                "last_position_observation_at": new_last_pos_obs,
                "real_submit_allowed": False,
            }

        return {
            **position,
            "first_position_observation_at": new_first_pos_obs,
            "last_position_observation_at": new_last_pos_obs,
            "real_submit_allowed": False,
        }

    # status in ("STOP_TRIGGERED", "STOP_EXIT_PARTIAL") — Golden #12/#13/#14。
    submitted_at_for_exit = position.get("stop_triggered_at")
    exit_result = sfm.evaluate_market_fill(
        side=exit_side, requested_qty=current_qty, observation=observation, now=now,
        submitted_at=submitted_at_for_exit,
    )
    incremental_exit = max(0, min(exit_result["filled_qty"], int(current_qty) if current_qty > 0 else 0))
    exit_filled_qty = position.get("exit_filled_qty")
    new_exit_filled = exit_filled_qty + incremental_exit
    new_current_qty = current_qty - incremental_exit

    previous_avg_exit = position.get("avg_exit_price")
    if incremental_exit > 0 and exit_result["avg_fill_price"] is not None:
        if previous_avg_exit is not None and exit_filled_qty > 0:
            avg_exit_price = (previous_avg_exit * exit_filled_qty
                               + exit_result["avg_fill_price"] * incremental_exit) / new_exit_filled
        else:
            avg_exit_price = exit_result["avg_fill_price"]
    else:
        avg_exit_price = previous_avg_exit

    new_first_stop_exit_fill_at = position.get("first_stop_exit_fill_at")
    new_last_stop_exit_fill_at = position.get("last_stop_exit_fill_at")
    if incremental_exit > 0:
        if new_first_stop_exit_fill_at is None:
            new_first_stop_exit_fill_at = observed_at
        new_last_stop_exit_fill_at = observed_at

    if new_current_qty <= 0:
        new_status = "CLOSED"
    elif new_exit_filled > 0:
        new_status = "STOP_EXIT_PARTIAL"
    else:
        new_status = status

    return {
        **position,
        "status": new_status,
        "current_qty": new_current_qty,
        "remaining_position_qty": new_current_qty,
        "exit_filled_qty": new_exit_filled,
        "avg_exit_price": avg_exit_price,
        "exit_reason": "STOP" if new_status == "CLOSED" else position.get("exit_reason"),
        "closed_at": observed_at if new_status == "CLOSED" else position.get("closed_at"),
        "fill_confidence": exit_result["fill_confidence"],
        "fill_reason": exit_result["fill_reason"],
        "best_bid": exit_result["best_bid"], "best_ask": exit_result["best_ask"],
        "bid_qty": exit_result["bid_qty"], "ask_qty": exit_result["ask_qty"],
        "spread_yen": exit_result["spread_yen"],
        "slippage_yen": exit_result["slippage_yen"], "slippage_bps": exit_result["slippage_bps"],
        "slippage_model_status": exit_result["slippage_model_status"],
        "first_stop_exit_fill_at": new_first_stop_exit_fill_at,
        "last_stop_exit_fill_at": new_last_stop_exit_fill_at,
        "first_position_observation_at": new_first_pos_obs,
        "last_position_observation_at": new_last_pos_obs,
        "real_submit_allowed": False,
    }
