"""scripts/shadow_execution.py

Shadow Execution Core（GitHub Issue #18 Execution Stack Phase 5.0、
C-057-GPT comment 5707721299 対応）。

Real brokerへ一切の副作用を出さない。Phase 1〜4.3で生成済みのcanonical
`Intent` / `RiskDecision` / `PermissionTicket`（`permission_status ==
"ORDER_TICKET_READY"`）の3点だけを入力として受け取り、
scripts/shadow_fill_model.py（Entry Fill Model v0.1）を使ってentryの
Shadow約定品質を決定論的に評価・記録する純粋関数群。broker/MS2/Excel/
networkへは直接アクセスしない。発注は一切行わない。

## Phase 5.0のスコープ境界
- ここではentry executionのみを扱う。protective stop・target・position
  lifecycle・Real-vs-Shadow reconciliation・calibration・Shadow Forward
  promotion・RssOrderはまだ実装しない（Phase 5.1以降で別レビュー）。
- `ORDER_TICKET_READY`はShadow入力可の必要条件だが、Real発注許可では
  ない。`CONFIRM_READY`をこのモジュールが代行生成することはない。
  human confirmationもこのモジュールが代行しない。
- Permission Gate / Kill switch / freshness / duplicate guardのロジック
  をここで別実装して矛盾させない——渡されたticket/Intent/RiskDecisionの
  lineage integrityを再確認するだけに留める。
- 実際のMS2由来のShadow order/fillイベントはdata/private/shadow/配下
  だけに置く（このファイル自体はpure coreであり、公開repoに置いてよい
  が、privateなfixture/イベントの永続化はここでは一切行わない——I/Oは
  このモジュールの外の責務）。
- data/private/trade_ledger.jsonl（Real ledger）はここでは一切参照・
  変更しない。Real ledgerとShadow ledgerを混ぜない。

## real_submit_allowedについて
このモジュールが返すどの辞書も`real_submit_allowed`は常にFalse固定。
これをTrueへ変更する経路は存在しない。

## Phase 5.0.1 hardening（3 blocker、C-057R-GPT comment 5707963859）
1. **partial fillの累積（Blocker 1）**：`evaluate_shadow_fill()`は毎回
   Fill Modelへ「まだ約定していない残数量」だけを渡し、その結果
   （incremental fill）を既存の`filled_qty`へ加算する。複数回の
   observationをまたぐpartial fillの累積が失われたり、既存fillが
   巻き戻されたりしない。`avg_fill_price`は複数回のfillをまたぐ
   数量加重平均。`new_total_filled`が`requested_qty`を超えることは
   防御的にcapして起こさない。
2. **shadow_fill_model_versionの完全binding（Blocker 2）**：
   `intent.shadow_fill_model_version`が実際に呼ぶ
   `scripts/shadow_fill_model.FILL_MODEL_VERSION`と完全一致することを
   必須にした。不一致（欠損・非string・不明・新旧いずれのversionも）は
   `REJECTED_SHADOW_FILL_MODEL_VERSION_MISMATCH`。将来v0.2を追加する
   時は明示的なversion routerを実装し、暗黙fallbackはしない。
3. **未モデル化slippageのNone化（Blocker 3）**：`scripts/shadow_fill_
   model.py`側の対応。fill成立時も`slippage_yen`/`slippage_bps`は
   実測/推定していない限り`None`のまま（0.0を書いて「計測したらゼロ
   だった」と誤記録しない）。`slippage_model_status="NOT_MODELED_V0_1"`
   を明示。

canonical field名は`status`のみに統一（`fill_status`という二重
フィールドは作らない）。

## Phase 5.0.2 chronology/state-integrity hardening（3 blocker、
C-060-GPT comment 5708285624）
1. **submitted_atのbind（Blocker 1）**：`submit_shadow_order()`が
   必須keyword-only引数`submitted_at`/`now`を受け取り、`submitted_at`を
   shadow orderのimmutable/bound contextとして保存する（内部で
   wall-clockを勝手に生成しない）。`evaluate_shadow_fill()`は外部から
   `submitted_at`を受け取らなくなり、order-bound値だけを使う——呼び出し
   側が別のsubmitted_atを注入して過去tradeを有効化する経路は存在しない。
   MARKET fillもLIMIT同様に`observation.observed_at <= submitted_at`を
   fillに使わないよう`scripts/shadow_fill_model.evaluate_market_fill()`
   へ`submitted_at`を追加した（従来MARKETだけsubmit前のquoteでもfill
   できた）。
2. **同一/古いobservationの二重計上防止（Blocker 2）**：orderに
   `last_applied_observation_at`を保持し、`observation.observed_at`が
   その値以下（同一timestampの再適用、または過去への巻き戻し）なら
   incremental fill=0のまま`fill_reason`に`DUPLICATE_OBSERVATION`/
   `OUT_OF_ORDER_OBSERVATION`を明示し、fillを一切適用しない。厳密に
   新しいobservationだけがfilled_qtyを前進させる。
3. **壊れたshadow stateのfail-closed化（Blocker 3）**：以前は
   `filled_qty`がNaN/負値等なら0へ黙って補正し処理を続けていた。
   `_validate_shadow_order_state()`が`requested_qty`（正整数）、
   `filled_qty`（`0<=filled_qty<=requested_qty`の整数）、
   `remaining_qty`の整合性、`filled_qty>0`なら`avg_fill_price`が
   finite positiveであること、`shadow_fill_model_version`一致、
   `real_submit_allowed is False`を検証し、いずれか1つでも違反すれば
   既存値を推測補正せず`REJECTED`（terminal）へ倒す。
"""
from __future__ import annotations

import hashlib
import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import execution_contract as ec
import shadow_fill_model as sfm

SCHEMA_VERSION = "shadow-execution-0.1"

ORDER_STATUSES = (
    "NEW",
    "ACCEPTED",
    "WORKING",
    "PARTIAL_FILLED",
    "FILLED",
    "EXPIRED",
    "REJECTED",
    "UNOBSERVABLE",
    "DUPLICATE_IGNORED",
)

# terminalな状態からは一切再評価しない（自動retryを表現しない、Golden #17）。
# REJECTED/DUPLICATE_IGNOREDはsubmit_shadow_order()の早期rejectパスが返す
# 最小フィールドの辞書（requested_qty/filled_qty等を持たない）なので、
# state-integrity検証（Blocker 3）の対象から明示的に除外する。
_MINIMAL_TERMINAL_STATUSES = frozenset({"REJECTED", "DUPLICATE_IGNORED"})
_FULL_TERMINAL_STATUSES = frozenset({"FILLED", "EXPIRED"})
_TERMINAL_STATUSES = _MINIMAL_TERMINAL_STATUSES | _FULL_TERMINAL_STATUSES


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def compute_shadow_order_id(intent_hash: str, shadow_fill_model_version: str) -> str:
    """`sha256(intent_hash + "|" + shadow_fill_model_version)`による決定論的
    ID。同一(intent_hash, fill_model_version)は常に同じIDになる
    （ランダムUUIDは使わない、Golden #1）。"""
    payload = f"{intent_hash}|{shadow_fill_model_version}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_lineage(intent, risk_decision, ticket) -> list[str]:
    """C-057-GPT section 2で明示された7条件 + lineage integrityの再確認。
    渡されたIntent/RiskDecision/ticketの型や中身を推測で補完しない。
    """
    reasons = []
    if not isinstance(intent, dict):
        return ["REJECTED_INTENT_INVALID_TYPE"]

    if intent.get("real_submit_allowed") is not False:
        reasons.append("REJECTED_REAL_SUBMIT_ALLOWED_NOT_FALSE")

    risk_ok = isinstance(risk_decision, dict) and risk_decision.get("decision") == "PASS"
    if not risk_ok:
        reasons.append("REJECTED_RISK_DECISION_NOT_PASS")

    ticket_ok = isinstance(ticket, dict) and ticket.get("permission_status") == "ORDER_TICKET_READY"
    if not ticket_ok:
        reasons.append("REJECTED_TICKET_NOT_READY")

    ticket_intent_hash = ticket.get("intent_hash") if isinstance(ticket, dict) else None
    if intent.get("intent_hash") != ticket_intent_hash:
        reasons.append("REJECTED_INTENT_HASH_MISMATCH")

    merge_hash = intent.get("merge_hash")
    risk_merge_hash = risk_decision.get("merge_hash") if isinstance(risk_decision, dict) else None
    ticket_merge_hash = ticket.get("merge_hash") if isinstance(ticket, dict) else None
    if not (merge_hash == risk_merge_hash == ticket_merge_hash):
        reasons.append("REJECTED_MERGE_HASH_MISMATCH")

    allowed_qty = risk_decision.get("allowed_qty") if isinstance(risk_decision, dict) else None
    if intent.get("quantity") != allowed_qty:
        reasons.append("REJECTED_QUANTITY_MISMATCH")

    risk_policy_version = risk_decision.get("policy_version") if isinstance(risk_decision, dict) else None
    if intent.get("risk_policy_version") != risk_policy_version:
        reasons.append("REJECTED_RISK_POLICY_VERSION_MISMATCH")

    if intent.get("side") not in ec.VALID_SIDES:
        reasons.append("REJECTED_SIDE_INVALID")
    if intent.get("order_type") not in ec.VALID_ORDER_TYPES:
        reasons.append("REJECTED_ORDER_TYPE_INVALID")

    # Phase 5.0.1 hardening（Blocker 2、C-057R-GPT comment 5707963859）:
    # 宣言されたshadow_fill_model_versionが、実際に呼ぶscripts/shadow_
    # fill_model.pyのFILL_MODEL_VERSIONと完全一致することを必須にする。
    # 不一致（欠損・非string・不明・新旧いずれのversionも）は暗黙fallback
    # せずREJECTEDにする——将来v0.2を追加する時は明示的なversion router
    # を実装し、ここでの暗黙一致緩和はしない。
    shadow_fill_model_version = intent.get("shadow_fill_model_version")
    if shadow_fill_model_version != sfm.FILL_MODEL_VERSION:
        reasons.append("REJECTED_SHADOW_FILL_MODEL_VERSION_MISMATCH")

    try:
        recomputed = ec.compute_intent_hash(intent)
    except Exception:  # noqa: BLE001 - 壊れたIntentは安全側でREJECTED
        reasons.append("REJECTED_INTENT_MALFORMED")
    else:
        if intent.get("intent_hash") != recomputed:
            reasons.append("REJECTED_INTENT_HASH_TAMPERED")

    return reasons


def _rejected(intent_hash, reasons: list[str]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "shadow_order_id": None,
        "intent_hash": intent_hash,
        "status": "REJECTED",
        "reject_reasons": sorted(set(reasons)),
        "real_submit_allowed": False,
    }


def submit_shadow_order(intent: dict, risk_decision: dict, ticket: dict, *, known_orders: list[dict],
                         submitted_at: datetime, now: datetime) -> dict:
    """Shadow orderを1件生成する純粋関数。lineageが不正ならREJECTED、
    同一(intent_hash, fill_model_version)が`known_orders`に既に存在すれば
    DUPLICATE_IGNOREDを返す——二重orderを作らない（Golden #2）。

    Phase 5.0.2 hardening（Blocker 1、C-060-GPT comment 5708285624）:
    `submitted_at`はここでshadow orderへimmutable/bound contextとして
    保存され、`evaluate_shadow_fill()`は以後この値だけを使う。この関数
    自体が内部でwall-clockを生成することはなく、`now`は呼び出し側が
    明示的に渡す（`submitted_at`のnaive/未来値をfail-closedするための
    基準時刻）。

    `known_orders`: 既知のshadow orderレコードのリスト（各要素は最低
    `shadow_order_id`を持つ辞書）。永続化はこの関数の外の責務。
    """
    intent_hash = intent.get("intent_hash") if isinstance(intent, dict) else None
    lineage_reasons = _validate_lineage(intent, risk_decision, ticket)

    if not isinstance(now, datetime) or now.tzinfo is None:
        lineage_reasons.append("REJECTED_NOW_NOT_TIMEZONE_AWARE")
    if not isinstance(submitted_at, datetime) or submitted_at.tzinfo is None:
        lineage_reasons.append("REJECTED_SUBMITTED_AT_NOT_TIMEZONE_AWARE")
    elif isinstance(now, datetime) and now.tzinfo is not None and submitted_at > now:
        lineage_reasons.append("REJECTED_SUBMITTED_AT_FUTURE")

    if lineage_reasons:
        return _rejected(intent_hash, lineage_reasons)

    if not isinstance(known_orders, list) or not all(isinstance(x, dict) for x in known_orders):
        return _rejected(intent_hash, ["REJECTED_KNOWN_ORDERS_INVALID"])

    shadow_fill_model_version = intent["shadow_fill_model_version"]
    shadow_order_id = compute_shadow_order_id(intent["intent_hash"], shadow_fill_model_version)

    for known in known_orders:
        if known.get("shadow_order_id") == shadow_order_id:
            return {
                "schema_version": SCHEMA_VERSION,
                "shadow_order_id": shadow_order_id,
                "intent_hash": intent_hash,
                "status": "DUPLICATE_IGNORED",
                "reject_reasons": [],
                "real_submit_allowed": False,
            }

    quantity = intent.get("quantity")
    return {
        "schema_version": SCHEMA_VERSION,
        "shadow_order_id": shadow_order_id,
        "intent_hash": intent_hash,
        "merge_hash": intent.get("merge_hash"),
        "ticket_fingerprint": ticket.get("ticket_fingerprint"),
        "shadow_fill_model_version": shadow_fill_model_version,
        "symbol": intent.get("symbol"),
        "side": intent.get("side"),
        "order_type": intent.get("order_type"),
        "limit_price": intent.get("limit_price"),
        "requested_qty": quantity,
        "filled_qty": 0,
        "remaining_qty": quantity,
        "reference_price": None,
        "avg_fill_price": None,
        "status": "NEW",
        "fill_confidence": None,
        "fill_reason": None,
        "best_bid": None, "best_ask": None, "bid_qty": None, "ask_qty": None,
        "spread_yen": None, "slippage_yen": None, "slippage_bps": None,
        "slippage_model_status": None,
        "submitted_at": submitted_at,
        "first_observation_at": None,
        "fill_at": None,
        "last_applied_observation_at": None,
        "ambiguity_flags": [],
        "reject_reasons": [],
        "real_submit_allowed": False,
    }


def _validate_shadow_order_state(shadow_order: dict) -> list[str]:
    """Phase 5.0.2 hardening（Blocker 3、C-060-GPT comment 5708285624）:
    永続化されたshadow orderの不変条件をfail-closedで検証する。違反が
    あれば既存値を推測補正せず、理由コードのリストを返す（空なら健全）。
    """
    reasons = []
    requested_qty = shadow_order.get("requested_qty")
    filled_qty = shadow_order.get("filled_qty")
    remaining_qty = shadow_order.get("remaining_qty")
    avg_fill_price = shadow_order.get("avg_fill_price")

    requested_ok = _is_finite_number(requested_qty) and requested_qty > 0 and int(requested_qty) == requested_qty
    if not requested_ok:
        reasons.append("REJECTED_STATE_REQUESTED_QTY_INVALID")

    filled_ok = _is_finite_number(filled_qty) and int(filled_qty) == filled_qty and filled_qty >= 0
    if filled_ok and requested_ok and filled_qty > requested_qty:
        filled_ok = False
    if not filled_ok:
        reasons.append("REJECTED_STATE_FILLED_QTY_INVALID")

    if requested_ok and filled_ok and remaining_qty != requested_qty - filled_qty:
        reasons.append("REJECTED_STATE_REMAINING_QTY_INCONSISTENT")

    if filled_ok and filled_qty > 0 and (not _is_finite_number(avg_fill_price) or avg_fill_price <= 0):
        reasons.append("REJECTED_STATE_AVG_FILL_PRICE_INVALID")

    if shadow_order.get("shadow_fill_model_version") != sfm.FILL_MODEL_VERSION:
        reasons.append("REJECTED_STATE_FILL_MODEL_VERSION_MISMATCH")

    if shadow_order.get("real_submit_allowed") is not False:
        reasons.append("REJECTED_STATE_REAL_SUBMIT_ALLOWED_NOT_FALSE")

    return reasons


def evaluate_shadow_fill(shadow_order: dict, observation: dict, *, now: datetime) -> dict:
    """既存のshadow_order（`submit_shadow_order()`の戻り値）へ、1件の
    MarketObservationを適用してentry fillを評価する純粋関数。terminal
    状態（FILLED/EXPIRED/REJECTED/DUPLICATE_IGNORED）からは一切再評価
    しない——自動retryは行わない（Golden #17）。新しいdictを返し、引数の
    `shadow_order`自体は書き換えない。

    Phase 5.0.1 hardening（Blocker 1、C-057R-GPT comment 5707963859）:
    Fill Modelへ渡す数量は常に「まだ約定していない残数量」であり、
    その結果（incremental fill）を既存のfilled_qtyへ加算する。以前は
    毎回requested_qty全量を渡し、結果でfilled_qtyを丸ごと上書きしていた
    ため、複数回のobservationにまたがるpartial fillの累積が失われて
    いた。avg_fill_priceは複数回のfillをまたぐ数量加重平均にする。

    Phase 5.0.2 hardening（C-060-GPT comment 5708285624）: `submitted_at`
    は外部から受け取らず、`shadow_order`自身のbound値だけを使う
    （Blocker 1）。`observation.observed_at`が`shadow_order.
    last_applied_observation_at`以下（同一/巻き戻り）ならfillを一切
    適用しない（Blocker 2）。state不変条件違反はREJECTEDへfail-closed
    する（Blocker 3）。
    """
    if not isinstance(shadow_order, dict):
        raise ValueError("shadow_order must be a dict")

    status = shadow_order.get("status")
    if status in _MINIMAL_TERMINAL_STATUSES:
        return dict(shadow_order)

    state_reasons = _validate_shadow_order_state(shadow_order)
    if state_reasons:
        return {
            **shadow_order,
            "status": "REJECTED",
            "reject_reasons": sorted(set(shadow_order.get("reject_reasons") or []) | set(state_reasons)),
            "real_submit_allowed": False,
        }

    if status in _FULL_TERMINAL_STATUSES:
        return dict(shadow_order)

    side = shadow_order.get("side")
    order_type = shadow_order.get("order_type")
    requested_qty = shadow_order.get("requested_qty")
    already_filled_qty = shadow_order.get("filled_qty")
    submitted_at = shadow_order.get("submitted_at")

    observed_at = observation.get("observed_at") if isinstance(observation, dict) else None
    last_applied = shadow_order.get("last_applied_observation_at")
    observed_at_valid = isinstance(observed_at, datetime) and observed_at.tzinfo is not None
    if observed_at_valid and last_applied is not None and observed_at <= last_applied:
        reason = "DUPLICATE_OBSERVATION" if observed_at == last_applied else "OUT_OF_ORDER_OBSERVATION"
        return {**shadow_order, "fill_reason": reason, "real_submit_allowed": False}

    remaining_before = requested_qty - already_filled_qty

    if order_type == "MARKET":
        result = sfm.evaluate_market_fill(side=side, requested_qty=remaining_before, observation=observation,
                                           now=now, submitted_at=submitted_at)
    elif order_type == "LIMIT":
        result = sfm.evaluate_limit_fill(
            side=side, requested_qty=remaining_before, limit_price=shadow_order.get("limit_price"),
            observation=observation, now=now, submitted_at=submitted_at,
        )
    else:
        result = sfm._base_result(observation if isinstance(observation, dict) else {}, fill_reason="ORDER_TYPE_INVALID")

    # Fill Modelはrequested_qty=remaining_before以下しか返さない設計だが、
    # new_total_filled > requested_qtyを絶対に起こさないよう防御的にcapする。
    incremental_fill = max(0, min(result["filled_qty"], int(remaining_before) if remaining_before > 0 else 0))
    new_total_filled = already_filled_qty + incremental_fill
    remaining_qty = requested_qty - new_total_filled

    previous_avg = shadow_order.get("avg_fill_price")
    if incremental_fill > 0 and result["avg_fill_price"] is not None:
        if previous_avg is not None and already_filled_qty > 0:
            avg_fill_price = (previous_avg * already_filled_qty + result["avg_fill_price"] * incremental_fill) / new_total_filled
        else:
            avg_fill_price = result["avg_fill_price"]
    else:
        avg_fill_price = previous_avg

    if new_total_filled <= 0:
        new_status = "UNOBSERVABLE" if result["fill_confidence"] == "UNOBSERVABLE" else "WORKING"
    elif remaining_qty > 0:
        new_status = "PARTIAL_FILLED"
    else:
        new_status = "FILLED"

    ambiguity_flags = []
    if result["fill_confidence"] in ("UNCERTAIN", "PROBABLE"):
        ambiguity_flags.append(result["fill_reason"])
    if 0 < new_total_filled < requested_qty:
        ambiguity_flags.append("PARTIAL_FILL")

    # このobservationが実際に処理された（submit後・有効なtimestamp）場合だけ
    # last_applied_observation_atを前進させる——過去への巻き戻りは起こさない。
    new_last_applied = last_applied
    if observed_at_valid and isinstance(submitted_at, datetime) and submitted_at.tzinfo is not None \
            and observed_at > submitted_at and (last_applied is None or observed_at > last_applied):
        new_last_applied = observed_at

    return {
        **shadow_order,
        "status": new_status,
        "filled_qty": new_total_filled,
        "remaining_qty": remaining_qty,
        "reference_price": result["reference_price"],
        "avg_fill_price": avg_fill_price,
        "fill_confidence": result["fill_confidence"],
        "fill_reason": result["fill_reason"],
        "best_bid": result["best_bid"], "best_ask": result["best_ask"],
        "bid_qty": result["bid_qty"], "ask_qty": result["ask_qty"],
        "spread_yen": result["spread_yen"],
        "slippage_yen": result["slippage_yen"],
        "slippage_bps": result["slippage_bps"],
        "slippage_model_status": result["slippage_model_status"],
        "first_observation_at": shadow_order.get("first_observation_at") or observed_at,
        "fill_at": observed_at if incremental_fill > 0 else shadow_order.get("fill_at"),
        "last_applied_observation_at": new_last_applied,
        "ambiguity_flags": ambiguity_flags,
        "real_submit_allowed": False,
    }
