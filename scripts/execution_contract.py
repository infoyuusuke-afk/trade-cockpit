"""scripts/execution_contract.py

Deterministic Execution Contract（GitHub Issue #18「Execution Stack Implementation
Plan v0.1」Phase 1、およびC-047-GPT「実装着手ゲート」への対応）。

これは発注そのものを一切行わない、純粋なIntent/Ticketのスキーマ・決定論的hash・
状態遷移だけを提供するモジュールである。broker/証券会社API・MarketSpeed II RSS
（RssOrder等）・Excelの注文式・自動submitは、このファイルにも将来のどのファイルにも
一切実装しない（CLAUDE.mdの「モデルの予測を自律的な売買注文に絶対に変換しない」
方針、および既存scripts/signal_contract.pyのtrading_enabled=False固定方針と同じ
境界をExecution側でも維持する）。

## このモジュールが作るもの
- build_intent(): Execution Intentの共通辞書を組み立てる純粋関数。BUY/SELLと
  MARKET/LIMITの正規化、必須項目・数量・価格の入力検証を行い、不正なら
  ValueErrorを送出する（自動修正・推定補完はしない）。
- compute_intent_hash(): 同一の意思決定内容なら常に同じ値になる決定論的hash。
  created_at・audit_id（監査用UUID）など非決定的なフィールドはhash対象に含めない。
- is_duplicate_intent(): 既存Intent集合に対してintent_hashが一致するかどうかだけを
  見る純粋関数（重複判定にUUIDは使わない——C-047の明示的な指示）。
- transition_status()/ALLOWED_TRANSITIONS: 状態遷移の許可表。許可されていない遷移は
  ValueErrorで拒否する。UNKNOWN状態から先への自動遷移は定義しない
  （＝自動再送を意味する遷移は存在しない）。

## real_submit_allowed について
build_intent()はreal_submit_allowedという引数自体を受け付けない。常にFalse固定の
値としてレコードへ書き込まれる。呼び出し側が万一この名前のキーワード引数を渡しても
TypeErrorになるだけで、値を上書きする経路が存在しない。
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

JST = timezone(timedelta(hours=9))
SCHEMA_VERSION = "execution-intent-1.0"

VALID_SIDES = ("BUY", "SELL")
VALID_ORDER_TYPES = ("MARKET", "LIMIT")

INTENT_STATUSES = (
    "CREATED",
    "RISK_BLOCKED",
    "PERMISSION_BLOCKED",
    "TICKET_READY",
    "AUTHORIZED",
    "SUBMITTING",
    "ACKNOWLEDGED",
    "PARTIAL",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "UNKNOWN",
)

# 状態遷移の許可表。値が空集合の状態は終端（そこから先への遷移は一切許可しない）。
# UNKNOWN（送信後に通信断・結果不明）から先への遷移が無いのは意図的——
# このcontract層は自動再送を一切表現しない。RISK_BLOCKED/PERMISSION_BLOCKEDも
# このレイヤーでは終端とし、再挑戦する場合は新しいIntentを作る前提にする
# （ブロック理由が解消したことにして同一Intentを使い回さない）。
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"RISK_BLOCKED", "PERMISSION_BLOCKED", "TICKET_READY"}),
    "TICKET_READY": frozenset({"AUTHORIZED"}),
    "AUTHORIZED": frozenset({"SUBMITTING"}),
    "SUBMITTING": frozenset({"ACKNOWLEDGED", "PARTIAL", "FILLED", "REJECTED", "CANCELLED", "UNKNOWN"}),
    "ACKNOWLEDGED": frozenset({"PARTIAL", "FILLED", "CANCELLED", "UNKNOWN"}),
    "PARTIAL": frozenset({"FILLED", "CANCELLED", "UNKNOWN"}),
    "RISK_BLOCKED": frozenset(),
    "PERMISSION_BLOCKED": frozenset(),
    "FILLED": frozenset(),
    "CANCELLED": frozenset(),
    "REJECTED": frozenset(),
    "UNKNOWN": frozenset(),
}

# intent_hashの対象フィールド（C-047-GPT固定仕様）。この順序はキーソートで
# 上書きされるため実際のhash値には影響しないが、意図を明示するために列挙しておく。
_HASH_FIELDS = (
    "symbol", "side", "quantity", "order_type", "limit_price",
    "planned_entry", "planned_stop", "strategy_id", "strategy_version",
    "decision_snapshot_id", "execution_policy_version",
)


def now_jst() -> datetime:
    return datetime.now(JST)


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_price(name: str, value: Optional[float], *, required: bool) -> None:
    if value is None:
        if required:
            raise ValueError(f"{name} is required and must not be None")
        return
    if not _is_finite_number(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value!r}")


def _canonical_json(payload: dict) -> bytes:
    """key-sorted・UTF-8・区切り記号固定のJSONバイト列（決定論的hashの入力）。"""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def compute_intent_hash(intent: dict) -> str:
    """intentの中からhash対象フィールドだけを取り出し、数値を正規化してSHA256する。
    created_at・audit_id・status・block_reasons・real_submit_allowedなど非決定的/
    可変な状態は一切含めない（C-047: timestampはhash対象に含めない）。
    """
    payload = {}
    for field in _HASH_FIELDS:
        value = intent.get(field)
        if field == "quantity" and value is not None:
            value = int(value)
        elif field in ("limit_price", "planned_entry", "planned_stop") and value is not None:
            value = float(value)
        payload[field] = value
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    return digest


def build_intent(
    *,
    symbol: str,
    side: str,
    quantity: int,
    order_type: str,
    strategy_id: str,
    strategy_version: str,
    decision_snapshot_id: str,
    signal_known_at: str,
    risk_policy_version: str,
    execution_policy_version: str,
    shadow_fill_model_version: str,
    merge_hash: str,
    limit_price: Optional[float] = None,
    planned_entry: Optional[float] = None,
    planned_stop: Optional[float] = None,
    planned_target: Optional[float] = None,
) -> dict:
    """Execution Intentを1件組み立てる純粋関数。不正な入力はValueErrorで拒否し、
    推測で補完しない。real_submit_allowedは引数として受け付けない
    （常にFalse固定でレコードへ書き込む）。

    Phase 4.3 lineage hardening（C-055R-GPT comment 5707245444）:
    `merge_hash`はConflict Resolver由来のRiskDecisionからそのままIntentへ
    引き継ぐ必須非空string。canonical `intent_hash`の対象フィールド
    （`_HASH_FIELDS`）には追加しない——Phase 4のexecution_permission.pyが
    `intent.merge_hash == risk_decision.merge_hash`を照合し、Intent↔
    RiskDecisionのlineageが正しく結合されているかをここで検証する
    （このモジュール自体はlineage検証をしない、値を運ぶだけ）。
    """
    if not symbol or not isinstance(symbol, str):
        raise ValueError("symbol is required and must be a non-empty string")
    if side not in VALID_SIDES:
        raise ValueError(f"side must be one of {VALID_SIDES}, got {side!r}")
    if order_type not in VALID_ORDER_TYPES:
        raise ValueError(f"order_type must be one of {VALID_ORDER_TYPES}, got {order_type!r}")
    if not _is_finite_number(quantity) or quantity <= 0 or int(quantity) != quantity:
        raise ValueError(f"quantity must be a positive integer, got {quantity!r}")
    if order_type == "LIMIT":
        _validate_price("limit_price", limit_price, required=True)
    else:  # MARKET
        if limit_price is not None:
            _validate_price("limit_price", limit_price, required=False)
    _validate_price("planned_entry", planned_entry, required=False)
    _validate_price("planned_stop", planned_stop, required=False)
    _validate_price("planned_target", planned_target, required=False)
    for name, value in (
        ("strategy_id", strategy_id), ("strategy_version", strategy_version),
        ("decision_snapshot_id", decision_snapshot_id), ("signal_known_at", signal_known_at),
        ("risk_policy_version", risk_policy_version),
        ("execution_policy_version", execution_policy_version),
        ("shadow_fill_model_version", shadow_fill_model_version),
        ("merge_hash", merge_hash),
    ):
        if not value or not isinstance(value, str):
            raise ValueError(f"{name} is required and must be a non-empty string")
    if parse_signal_known_at(signal_known_at) is None:
        raise ValueError(f"signal_known_at must be a parseable timestamp, got {signal_known_at!r}")

    intent = {
        "schema_version": SCHEMA_VERSION,
        "audit_id": uuid.uuid4().hex,
        "created_at": now_jst().isoformat(),
        "symbol": symbol,
        "side": side,
        "quantity": int(quantity),
        "order_type": order_type,
        "limit_price": None if limit_price is None else float(limit_price),
        "planned_entry": None if planned_entry is None else float(planned_entry),
        "planned_stop": None if planned_stop is None else float(planned_stop),
        "planned_target": None if planned_target is None else float(planned_target),
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "decision_snapshot_id": decision_snapshot_id,
        "signal_known_at": signal_known_at,
        "risk_policy_version": risk_policy_version,
        "execution_policy_version": execution_policy_version,
        "shadow_fill_model_version": shadow_fill_model_version,
        "merge_hash": merge_hash,
        "status": "CREATED",
        "block_reasons": [],
        "real_submit_allowed": False,
    }
    intent["intent_hash"] = compute_intent_hash(intent)
    return intent


def parse_signal_known_at(text: str) -> Optional[datetime]:
    """signal_known_atのISO8601文字列を解析する。不正/空ならNone（推測補完しない）。"""
    if not text or not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def is_duplicate_intent(candidate: dict, existing: list[dict]) -> bool:
    """intent_hashの完全一致だけで重複判定する純粋関数（fuzzy matchはしない）。"""
    candidate_hash = candidate.get("intent_hash") or compute_intent_hash(candidate)
    return any(e.get("intent_hash") == candidate_hash for e in existing)


def transition_status(current: str, target: str) -> str:
    """current→targetの遷移が許可表に無ければValueErrorで拒否する純粋関数。
    許可されていれば新しい状態文字列を返す（呼び出し側でintent["status"]へ代入する）。
    """
    if current not in ALLOWED_TRANSITIONS:
        raise ValueError(f"unknown current status: {current!r}")
    if target not in INTENT_STATUSES:
        raise ValueError(f"unknown target status: {target!r}")
    allowed = ALLOWED_TRANSITIONS[current]
    if target not in allowed:
        raise ValueError(
            f"transition {current!r} -> {target!r} is not allowed "
            f"(allowed targets from {current!r}: {sorted(allowed) or 'none (terminal state)'})"
        )
    return target
