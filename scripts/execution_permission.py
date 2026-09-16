"""scripts/execution_permission.py

Execution Permission / Kill Switch / Price Drift Guard（GitHub Issue #18
Execution Stack Phase 4、base design C-055 comment 5702335837 +
C-053-GPT comment 5704719373の上書き条件への対応）。

canonical pipeline:
    Signal → Conflict Resolver → Risk Gate(PASS/qty)
      → execution_contract.build_intent()
      → [このファイル] Permission/Kill/Duplicate Guard → ORDER_TICKET_READY

**このファイルは注文を送らない。** RssOrder・Excel注文式・broker submit・
実ポジション変更は一切実装しない。broker/MS2/Excel/networkへ直接取りに
行かず、必要な状態（口座・kill switch・quote・duplicate台帳等）は全て
引数として受け取る純粋関数だけを提供する。wall-clock（`datetime.now()`）
は判定関数の内部で一切呼ばない——`now`は呼び出し側が明示的に渡す。

## C-053-GPTによる上書き解釈（重要）
1. canonical `intent_hash`を再定義しない。scripts/execution_contract.py
   の`compute_intent_hash()`だけがcanonical。ここでは渡されたIntentの
   `intent_hash`が改ざんされていないか（`compute_intent_hash(intent)`と
   再計算一致するか）を検証するだけで、新しいhash方式は作らない。
2. `real_submit_allowed`は最後までFalse固定。Phase 4がPASSしても
   Intentの`real_submit_allowed`をTrueへ書き換えない・出力にもTrueを
   一切含めない。Phase 4のPASS結果は別フィールド`permission_status`
   （例: `ORDER_TICKET_READY`）として表現する。
3. Permission Gateは既存Intent + RiskDecision + 外部snapshotを読むだけ。
4. ALL-PASS方式：1つでもFalse/UNKNOWN/missing/staleならBLOCKED。
5. MASTER_KILLはdefault DISARMED。`default_kill_switch_state()`は常に
   DISARMEDを返す——プロセス起動時は必ずこの関数を呼ぶことで、永続化された
   古いARMED状態を誤って復元しない設計にする（自動再ARM禁止）。
6. Duplicate/UNKNOWNは再送禁止（scripts/order_guard.pyに委譲）。
7. Price Drift Guardは2箇所で確認する：①ORDER_TICKET_READY生成直前
   （`evaluate_permission()`）、②human confirm直前
   （`evaluate_reconfirmation()`）。基準超過は`EXPIRED_REQUOTE_REQUIRED`
   とし、既存Intentを書き換えず新しいIntentを作り直す前提にする。
8. TTL/freshness判定に使う時刻は全てtimezone-aware必須。naiveはBLOCK。
9. human confirmationは`intent_hash`だけでなく、RiskDecision lineage・
   quote鮮度・authorization・broker snapshot・policy versionを含む
   `ticket_fingerprint`に結び付ける。fingerprintが変わったら再確認必須。
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import execution_contract as ec
import order_guard as og

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = ROOT / "config" / "execution_safety_v0_1.json"
SCHEMA_VERSION = "execution-permission-1.0"

PERMISSION_STATUSES = ("ORDER_TICKET_READY", "BLOCKED", "EXPIRED_REQUOTE_REQUIRED")
RECONFIRM_STATUSES = ("CONFIRM_READY", "RECONFIRM_REQUIRED", "EXPIRED_REQUOTE_REQUIRED", "BLOCKED")


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict:
    """execution_safety_v0_1.jsonを読む（I/Oはここだけに閉じ込める）。"""
    return json.loads(path.read_text(encoding="utf-8"))


def default_kill_switch_state() -> dict:
    """プロセス起動時に必ず呼ぶ安全な初期状態。常にDISARMEDを返す——
    呼び出し側がこれを使わず、永続化した過去のARMED状態をそのまま
    復元すると「再起動後の自動再ARM禁止」という安全境界が壊れる。
    """
    return {"status": "DISARMED", "armed_at": None, "expires_at": None}


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and _finite(value)


def _finite(value) -> bool:
    import math
    return math.isfinite(value)


def _parse_aware(text) -> Optional[datetime]:
    """offset-aware ISO8601のみ受け付ける。naive/不正/欠損はNoneを返し
    （呼び出し側がBLOCK扱いにする）、推測でタイムゾーンを補完しない。"""
    if not text or not isinstance(text, str):
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def check_master_kill(kill_state: dict, *, now: datetime) -> tuple[bool, list[str]]:
    """master kill switchがARMEDかつ有効期限内かを確認する純粋関数。
    デフォルト（default_kill_switch_state()）はDISARMEDなので、呼び出し側が
    明示的にARMED状態を渡さない限り常にBLOCKされる。
    """
    if not isinstance(kill_state, dict) or kill_state.get("status") != "ARMED":
        return False, ["BLOCK_MASTER_KILL_DISARMED"]
    expires_at = _parse_aware(kill_state.get("expires_at"))
    if expires_at is None:
        return False, ["BLOCK_MASTER_KILL_EXPIRY_INVALID"]
    if expires_at <= now:
        return False, ["BLOCK_MASTER_KILL_EXPIRED"]
    return True, []


def check_price_drift(*, planned_entry: float, quote_price: float, quote_asof: str,
                       ticket_created_at: str, now: datetime, policy: dict) -> tuple[bool, list[str]]:
    """quoteの鮮度とplanned entryからの価格乖離を確認する。Signal生成時だけ
    でなく、Phase 4の2箇所（ticket生成直前・human confirm直前）で同じ
    ロジックを呼ぶことを想定する（C-053第7節）。
    """
    reasons = []
    quote_ts = _parse_aware(quote_asof)
    ticket_ts = _parse_aware(ticket_created_at)
    if quote_ts is None or ticket_ts is None:
        return False, ["BLOCK_TIMESTAMP_NOT_TIMEZONE_AWARE"]
    if not _is_finite_number(planned_entry) or planned_entry <= 0:
        return False, ["BLOCK_PLANNED_ENTRY_INVALID"]
    if not _is_finite_number(quote_price) or quote_price <= 0:
        return False, ["BLOCK_QUOTE_PRICE_INVALID"]

    ticket_age_sec = (now - ticket_ts).total_seconds()
    if ticket_age_sec < 0 or ticket_age_sec > policy["max_ticket_age_sec"]:
        reasons.append("EXPIRED_TICKET_AGE")
    quote_age_sec = (now - quote_ts).total_seconds()
    if quote_age_sec < 0 or quote_age_sec > policy["max_ticket_age_sec"]:
        reasons.append("EXPIRED_QUOTE_STALE")

    drift_bps = abs(quote_price - planned_entry) / planned_entry * 10000
    if drift_bps > policy["max_price_drift_bps"]:
        reasons.append("EXPIRED_PRICE_DRIFT")

    return (len(reasons) == 0), reasons


def compute_ticket_fingerprint(*, intent_hash: str, merge_hash: str, risk_policy_version: str,
                                allowed_qty: int, quote_price: float, quote_asof: str,
                                authorization_session_id: str, authorization_expires_at: str,
                                broker_snapshot_fingerprint: str, permission_policy_version: str) -> str:
    """human confirmationを結び付けるための決定論的fingerprint。canonical
    `intent_hash`とは別物（C-053第9節）——RiskDecision lineage・quote鮮度・
    authorization・broker snapshot・permission policy versionをまとめて
    1つのhashにすることで、そのどれか1つでも変わったら再確認が必要になる。
    """
    payload = {
        "intent_hash": intent_hash,
        "merge_hash": merge_hash,
        "risk_policy_version": risk_policy_version,
        "allowed_qty": int(allowed_qty),
        "quote_price": float(quote_price),
        "quote_asof": quote_asof,
        "authorization_session_id": authorization_session_id,
        "authorization_expires_at": authorization_expires_at,
        "broker_snapshot_fingerprint": broker_snapshot_fingerprint,
        "permission_policy_version": permission_policy_version,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate_permission(intent: dict, risk_decision: dict, snapshot: dict, policy: dict,
                         *, now: datetime) -> dict:
    """Permission Gateの中核となる純粋関数。ALL-PASS方式——1つでもゲートが
    False/UNKNOWN/missing/staleならBLOCKED。同一入力からは常に同一の
    PermissionDecisionを返す（nowは明示引数、内部でdatetime.now()を呼ばない）。

    intent: scripts/execution_contract.build_intent()が返すExecution
        Intent。real_submit_allowedは常にFalseである前提（このファイルは
        それをTrueへ書き換えない）。
    risk_decision: scripts/risk_gate.evaluate_risk()が返すRiskDecision。
    snapshot: 呼び出し側が別途集計するbroker/session/quote/kill-switch等の
        外部状態スナップショット（このファイルはbroker/RSS等へ取りに
        行かない）。必須キーは docstring内の各チェックを参照。
    policy: load_policy()が返す辞書。
    """
    base = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": policy.get("policy_version"),
        "generated_at": now.isoformat(),
        "intent_hash": intent.get("intent_hash") if isinstance(intent, dict) else None,
        "symbol": intent.get("symbol") if isinstance(intent, dict) else None,
        "permission_status": None,
        "ticket_fingerprint": None,
        "block_reasons": [],
    }

    # --- 0. Intentの完全性検証（改ざん検知） -------------------------------
    if not isinstance(intent, dict):
        return {**base, "permission_status": "BLOCKED", "block_reasons": ["BLOCK_INTENT_INVALID_TYPE"]}
    try:
        recomputed = ec.compute_intent_hash(intent)
    except Exception:  # noqa: BLE001 - 壊れたIntentは安全側でBLOCK
        return {**base, "permission_status": "BLOCKED", "block_reasons": ["BLOCK_INTENT_MALFORMED"]}
    if intent.get("intent_hash") != recomputed:
        return {**base, "permission_status": "BLOCKED", "block_reasons": ["BLOCK_INTENT_HASH_TAMPERED"]}
    # real_submit_allowedは絶対にTrueへ書き換えない。入力が既にTrueへ
    # 改ざんされていた場合も、このGate自体がTrueを作る経路を持たないことで
    # 安全側に倒す（execution_contract側のFalse固定と二重の防御になる）。
    if intent.get("real_submit_allowed") is not False:
        return {**base, "permission_status": "BLOCKED", "block_reasons": ["BLOCK_REAL_SUBMIT_ALLOWED_TAMPERED"]}

    # --- 1. Price drift（ticket生成直前のチェックポイント①、最優先で短絡） ---
    # 他のゲートより先に判定する。価格が乖離/失効している時点でこのIntentは
    # 使い回せない（新しいIntentをやり直す）ため、他の理由と混ぜて曖昧にする
    # より、まず明確にEXPIRED_REQUOTE_REQUIREDを返す方が呼び出し側の動作が
    # 単純になる（再取得後の再評価では他のゲートも当然に再チェックされる）。
    quote_price = snapshot.get("quote_price")
    quote_asof = snapshot.get("quote_asof")
    ticket_created_at = snapshot.get("ticket_created_at")
    planned_entry = intent.get("planned_entry") if intent.get("planned_entry") is not None else intent.get("limit_price")
    drift_ok, drift_reasons = check_price_drift(
        planned_entry=planned_entry, quote_price=quote_price, quote_asof=quote_asof,
        ticket_created_at=ticket_created_at, now=now, policy=policy,
    )
    if not drift_ok:
        return {**base, "permission_status": "EXPIRED_REQUOTE_REQUIRED", "block_reasons": drift_reasons}

    reasons = []

    # --- 2. Risk Gate ------------------------------------------------------
    if not isinstance(risk_decision, dict) or risk_decision.get("decision") != "PASS":
        reasons.append("BLOCK_RISK_GATE_NOT_PASS")

    # --- 3. Master Kill ------------------------------------------------------
    kill_ok, kill_reasons = check_master_kill(snapshot.get("kill_switch", {}), now=now)
    if not kill_ok:
        reasons.extend(kill_reasons)

    # --- 4. Human Authorization ---------------------------------------------
    if snapshot.get("human_session_authorized") is not True:
        reasons.append("BLOCK_HUMAN_AUTHORIZATION_MISSING")
    auth_expiry = _parse_aware(snapshot.get("authorization_expires_at"))
    if auth_expiry is None:
        reasons.append("BLOCK_AUTHORIZATION_EXPIRY_INVALID")
    elif auth_expiry <= now:
        reasons.append("BLOCK_AUTHORIZATION_EXPIRED")

    # --- 5. Data freshness / session / tradeability -------------------------
    if snapshot.get("data_freshness") != "OK":
        reasons.append("BLOCK_DATA_FRESHNESS_NOT_OK")
    if snapshot.get("market_session_allowed") is not True:
        reasons.append("BLOCK_MARKET_SESSION_NOT_ALLOWED")
    if snapshot.get("symbol_tradeable") is not True:
        reasons.append("BLOCK_SYMBOL_NOT_TRADEABLE")
    if snapshot.get("broker_link_health") != "OK":
        reasons.append("BLOCK_BROKER_LINK_UNHEALTHY")

    # --- 6. Position reconciliation / buying power / shortable -------------
    recon_blocked, recon_reasons = og.check_position_reconciliation(
        snapshot.get("expected_position_qty"), snapshot.get("broker_position_qty"))
    if recon_blocked:
        reasons.extend(recon_reasons)
    if snapshot.get("buying_power_check") is not True:
        reasons.append("BLOCK_BUYING_POWER_NOT_CONFIRMED")
    if intent.get("side") == "SELL" and snapshot.get("short_availability_check") is not True:
        reasons.append("BLOCK_SHORT_AVAILABILITY_NOT_CONFIRMED")

    # --- 7. Daily loss / max positions（Risk Gate通過後もdefense-in-depthで再確認） --
    realized_pnl_today = snapshot.get("realized_pnl_today_yen")
    if not _is_finite_number(realized_pnl_today):
        reasons.append("BLOCK_REALIZED_PNL_UNKNOWN")
    elif max(0.0, -realized_pnl_today) >= policy["daily_stop_yen"]:
        reasons.append("BLOCK_DAILY_STOP_REACHED")
    open_positions_count = snapshot.get("open_positions_count")
    if not _is_finite_number(open_positions_count):
        reasons.append("BLOCK_OPEN_POSITIONS_COUNT_UNKNOWN")
    elif open_positions_count >= policy["max_open_positions"]:
        reasons.append("BLOCK_MAX_OPEN_POSITIONS_REACHED")

    # --- 8. Duplicate / pending guard ---------------------------------------
    dup_blocked, dup_reasons = og.is_duplicate_submission(
        intent["intent_hash"], snapshot.get("known_intents", []))
    if dup_blocked:
        reasons.extend(dup_reasons)
    pending_blocked, pending_reasons = og.check_pending_duplicate(
        intent.get("symbol"), intent.get("side"), snapshot.get("pending_orders", []))
    if pending_blocked:
        reasons.extend(pending_reasons)

    # --- 9. Order fields / tick / lot（外部が精査した結果を受け取るだけ） -----
    if snapshot.get("price_tick_valid") is not True:
        reasons.append("BLOCK_PRICE_TICK_INVALID")
    if snapshot.get("qty_lot_valid") is not True:
        reasons.append("BLOCK_QTY_LOT_INVALID")

    if reasons:
        return {**base, "permission_status": "BLOCKED", "block_reasons": sorted(set(reasons))}

    fingerprint = compute_ticket_fingerprint(
        intent_hash=intent["intent_hash"],
        merge_hash=risk_decision.get("merge_hash"),
        risk_policy_version=risk_decision.get("policy_version"),
        allowed_qty=risk_decision.get("allowed_qty"),
        quote_price=quote_price, quote_asof=quote_asof,
        authorization_session_id=snapshot.get("authorization_session_id"),
        authorization_expires_at=snapshot.get("authorization_expires_at"),
        broker_snapshot_fingerprint=snapshot.get("broker_snapshot_fingerprint"),
        permission_policy_version=policy.get("policy_version"),
    )
    return {**base, "permission_status": "ORDER_TICKET_READY", "ticket_fingerprint": fingerprint}


def evaluate_reconfirmation(ticket: dict, fresh_snapshot: dict, policy: dict, *, now: datetime) -> dict:
    """human confirmを受け付ける直前のチェックポイント②（C-053第7節・第9節）。
    ticketはevaluate_permission()がORDER_TICKET_READYを返した結果そのもの。
    fresh_snapshotはconfirm時点で取り直したquote/authorization/broker状態。
    fingerprintが変わっていれば再確認必須、priceが乖離/失効していれば
    EXPIRED_REQUOTE_REQUIRED（新しいIntentをやり直す）。
    """
    base = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": policy.get("policy_version"),
        "generated_at": now.isoformat(),
        "intent_hash": ticket.get("intent_hash"),
        "reconfirm_status": None,
        "block_reasons": [],
    }
    if ticket.get("permission_status") != "ORDER_TICKET_READY":
        return {**base, "reconfirm_status": "BLOCKED", "block_reasons": ["BLOCK_TICKET_NOT_READY"]}

    quote_price = fresh_snapshot.get("quote_price")
    quote_asof = fresh_snapshot.get("quote_asof")
    ticket_created_at = fresh_snapshot.get("ticket_created_at")
    planned_entry = fresh_snapshot.get("planned_entry")
    drift_ok, drift_reasons = check_price_drift(
        planned_entry=planned_entry, quote_price=quote_price, quote_asof=quote_asof,
        ticket_created_at=ticket_created_at, now=now, policy=policy,
    )
    if not drift_ok:
        return {**base, "reconfirm_status": "EXPIRED_REQUOTE_REQUIRED", "block_reasons": drift_reasons}

    fresh_fingerprint = compute_ticket_fingerprint(
        intent_hash=ticket.get("intent_hash"),
        merge_hash=fresh_snapshot.get("merge_hash"),
        risk_policy_version=fresh_snapshot.get("risk_policy_version"),
        allowed_qty=fresh_snapshot.get("allowed_qty"),
        quote_price=quote_price, quote_asof=quote_asof,
        authorization_session_id=fresh_snapshot.get("authorization_session_id"),
        authorization_expires_at=fresh_snapshot.get("authorization_expires_at"),
        broker_snapshot_fingerprint=fresh_snapshot.get("broker_snapshot_fingerprint"),
        permission_policy_version=policy.get("policy_version"),
    )
    if fresh_fingerprint != ticket.get("ticket_fingerprint"):
        return {**base, "reconfirm_status": "RECONFIRM_REQUIRED", "block_reasons": ["TICKET_FINGERPRINT_CHANGED"]}

    return {**base, "reconfirm_status": "CONFIRM_READY", "block_reasons": []}
