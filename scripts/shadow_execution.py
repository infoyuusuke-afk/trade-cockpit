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
_TERMINAL_STATUSES = frozenset({"FILLED", "EXPIRED", "REJECTED", "DUPLICATE_IGNORED"})


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

    shadow_fill_model_version = intent.get("shadow_fill_model_version")
    if not shadow_fill_model_version or not isinstance(shadow_fill_model_version, str):
        reasons.append("REJECTED_SHADOW_FILL_MODEL_VERSION_MISSING")

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


def submit_shadow_order(intent: dict, risk_decision: dict, ticket: dict, *, known_orders: list[dict]) -> dict:
    """Shadow orderを1件生成する純粋関数。lineageが不正ならREJECTED、
    同一(intent_hash, fill_model_version)が`known_orders`に既に存在すれば
    DUPLICATE_IGNOREDを返す——二重orderを作らない（Golden #2）。

    `known_orders`: 既知のshadow orderレコードのリスト（各要素は最低
    `shadow_order_id`を持つ辞書）。永続化はこの関数の外の責務。
    """
    intent_hash = intent.get("intent_hash") if isinstance(intent, dict) else None
    lineage_reasons = _validate_lineage(intent, risk_decision, ticket)
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
        "first_observation_at": None,
        "fill_at": None,
        "ambiguity_flags": [],
        "reject_reasons": [],
        "real_submit_allowed": False,
    }


def evaluate_shadow_fill(shadow_order: dict, observation: dict, *, now: datetime, submitted_at: datetime) -> dict:
    """既存のshadow_order（`submit_shadow_order()`の戻り値）へ、1件の
    MarketObservationを適用してentry fillを評価する純粋関数。terminal
    状態（FILLED/EXPIRED/REJECTED/DUPLICATE_IGNORED）からは一切再評価
    しない——自動retryは行わない（Golden #17）。新しいdictを返し、引数の
    `shadow_order`自体は書き換えない。
    """
    if not isinstance(shadow_order, dict):
        raise ValueError("shadow_order must be a dict")
    if shadow_order.get("status") in _TERMINAL_STATUSES:
        return dict(shadow_order)

    side = shadow_order.get("side")
    order_type = shadow_order.get("order_type")
    requested_qty = shadow_order.get("requested_qty")

    if order_type == "MARKET":
        result = sfm.evaluate_market_fill(side=side, requested_qty=requested_qty, observation=observation, now=now)
    elif order_type == "LIMIT":
        result = sfm.evaluate_limit_fill(
            side=side, requested_qty=requested_qty, limit_price=shadow_order.get("limit_price"),
            observation=observation, now=now, submitted_at=submitted_at,
        )
    else:
        result = sfm._base_result(observation if isinstance(observation, dict) else {}, fill_reason="ORDER_TYPE_INVALID")

    filled_qty = result["filled_qty"]
    remaining_qty = (requested_qty - filled_qty) if _is_finite_number(requested_qty) else None

    if result["fill_confidence"] == "UNOBSERVABLE":
        status = "UNOBSERVABLE"
    elif filled_qty <= 0:
        status = "WORKING"
    elif remaining_qty is not None and remaining_qty > 0:
        status = "PARTIAL_FILLED"
    else:
        status = "FILLED"

    ambiguity_flags = []
    if result["fill_confidence"] in ("UNCERTAIN", "PROBABLE"):
        ambiguity_flags.append(result["fill_reason"])
    if _is_finite_number(requested_qty) and 0 < filled_qty < requested_qty:
        ambiguity_flags.append("PARTIAL_FILL")

    observed_at = observation.get("observed_at") if isinstance(observation, dict) else None

    return {
        **shadow_order,
        "status": status,
        "filled_qty": filled_qty,
        "remaining_qty": remaining_qty,
        "reference_price": result["reference_price"],
        "avg_fill_price": result["avg_fill_price"],
        "fill_confidence": result["fill_confidence"],
        "fill_reason": result["fill_reason"],
        "best_bid": result["best_bid"], "best_ask": result["best_ask"],
        "bid_qty": result["bid_qty"], "ask_qty": result["ask_qty"],
        "spread_yen": result["spread_yen"],
        "slippage_yen": result["slippage_yen"],
        "slippage_bps": result["slippage_bps"],
        "first_observation_at": shadow_order.get("first_observation_at") or observed_at,
        "fill_at": observed_at if filled_qty > 0 else shadow_order.get("fill_at"),
        "ambiguity_flags": ambiguity_flags,
        "real_submit_allowed": False,
    }
