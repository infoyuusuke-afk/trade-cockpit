"""scripts/execution_permission.py

Execution Permission / Kill Switch / Price Drift Guard（GitHub Issue #18
Execution Stack Phase 4、base design C-055 comment 5702335837 +
C-053-GPT comment 5704719373 + Phase 4.1 hardening C-053R-GPT comment
5705124424の上書き条件への対応）。

canonical pipeline:
    Signal → Conflict Resolver → Risk Gate(PASS/qty)
      → execution_contract.build_intent()
      → [このファイル] Permission/Kill/Duplicate Guard → ORDER_TICKET_READY

**このファイルは注文を送らない。** RssOrder・Excel注文式・broker submit・
実ポジション変更は一切実装しない。broker/MS2/Excel/networkへ直接取りに
行かず、必要な状態（口座・kill switch・quote・duplicate台帳等）は全て
引数として受け取る純粋関数だけを提供する。wall-clock（`datetime.now()`）
は判定関数の内部で一切呼ばない——`now`は呼び出し側が明示的に渡す。

## C-053-GPTによる上書き解釈
1. canonical `intent_hash`を再定義しない。`compute_intent_hash()`だけが
   canonical。ここでは渡されたIntentの`intent_hash`が改ざんされていない
   か（再計算一致するか）を検証するだけ。
2. `real_submit_allowed`は最後までFalse固定。成功は別フィールド
   `permission_status`（`ORDER_TICKET_READY`）として表現する。
3. Permission Gateは既存Intent + RiskDecision + 外部snapshotを読むだけ。
4. ALL-PASS方式：1つでもFalse/UNKNOWN/missing/staleならBLOCKED。
5. MASTER_KILLはdefault DISARMED。`default_kill_switch_state()`は常に
   DISARMEDを返す。
6. Duplicate/UNKNOWNは再送禁止（scripts/order_guard.pyに委譲）。
7. Price Drift Guardは2箇所で確認する。基準超過は`EXPIRED_REQUOTE_
   REQUIRED`とし、既存Intentを書き換えず新しいIntentを作り直す前提。
8. TTL/freshness判定に使う時刻は全てtimezone-aware必須。
9. human confirmationは`ticket_fingerprint`に結び付ける。

## Phase 4.1 hardening（5 blocker、C-053R-GPT）
1. **Intent/RiskDecisionのlineage結合**：`risk_decision.decision==PASS`
   だけでなく、symbol/side/quantity(=allowed_qty)/risk_policy_versionの
   完全一致、merge_hashの非空性、allowed_qtyの正整数性、conflict_state
   （snapshotの明示入力）を検証する。どれか1つでも不一致なら
   `BLOCK_RISK_LINEAGE_MISMATCH`等でfail closed。
2. **reconfirmationで全ゲートを再評価**：`evaluate_reconfirmation()`は
   `evaluate_permission()`と同じゲート群（`_evaluate_all_gates()`）を
   fresh snapshotに対して再実行してからprice drift/fingerprintを見る。
   `planned_entry`はIntentを正とし、`ticket_created_at`相当は
   （Phase 4.2でticket-bound値`ticket["intent_created_at"]`に変更、
   下記参照）fresh snapshot側からは一切受け取らない——古いticketを
   fresh snapshotの値で若く見せかけられない。
3. **execution safety policyのv0.1 envelope固定**：
   `validate_execution_policy_v0_1()`でpolicy_version完全一致・
   各TTL/上限のv0.1範囲（縮小のみ許可）・非dict/NaN/inf/bool/型不正を
   例外を投げずBLOCKにする。MASTER_KILLは`armed_at`〜`expires_at`が
   `master_kill_ttl_sec`以内であることを、Human Authorizationは
   `authorization_issued_at`〜`authorization_expires_at`が
   `authorization_ttl_sec`以内であることを実際に検証する。
4. **timezone/input fail-closedの完全化**：`now`自体のaware必須化、
   Intentの`signal_known_at`のaware必須化・未来禁止、`snapshot`の
   dict型必須化、`known_intents`/`pending_orders`のlist[dict]必須化、
   `authorization_session_id`/`broker_snapshot_fingerprint`の非空必須化。
5. **REJECTED/CANCELLEDの再利用禁止**：scripts/order_guard.py側で対応
   （TICKET_READY以降に到達したintent_hashは一切再利用しない）。

## Phase 4.2 hardening（2 blocker + 1 small hardening、C-054R-GPT comment
   5705359392）
1. **intent_created_at/signal_known_atのticket-bind（Blocker 1）**：
   canonical `intent_hash`はcreated_at/signal_known_atを含まないため、
   ticket発行後にIntentオブジェクト側のこの2フィールドだけを書き換えても
   hash一致のままticket ageを若く見せかけられる。`evaluate_permission()`
   はticket発行時のこの2値を`ticket_fingerprint`のpayloadに含めつつ、
   ticket dictの新フィールド`intent_created_at`/`signal_known_at`にも
   保存する。`evaluate_reconfirmation()`は現在のIntentの値をこの
   ticket-bound値と比較し、不一致なら`BLOCK_INTENT_CREATED_AT_MISMATCH`/
   `BLOCK_SIGNAL_KNOWN_AT_MISMATCH`でBLOCKする。price drift計算の
   `ticket_created_at`も常に`ticket.get("intent_created_at")`（ticket-bound
   値）を使い、mutableな`intent.get("created_at")`を直接使わない。
2. **authorization_issued_atの未来禁止・順序検証（Blocker 2）**：
   `check_authorization()`に`issued_at > now`（`BLOCK_AUTHORIZATION_
   ISSUED_AT_FUTURE`）と`expires_at <= issued_at`（`BLOCK_AUTHORIZATION_
   EXPIRY_BEFORE_ISSUED`）を追加。`authorization_issued_at`も
   `ticket_fingerprint`へ含める（fresh_snapshot側から都度読み直すため、
   正当な再認証はfingerprint不一致→RECONFIRM_REQUIREDとして検出される）。
3. **open_positions_countの離散値検証（small hardening）**：finiteなだけ
   では-1や0.5を通してしまうため、0以上の整数のみを許可する
   （`BLOCK_OPEN_POSITIONS_COUNT_UNKNOWN`）。physical position quantityの
   離散値検証はscripts/order_guard.pyの`check_position_reconciliation()`
   側で対応（整数のみ許可）。

## Phase 4.3 lineage hardening（C-055R-GPT comment 5707245444）
Conflict Resolver由来の`merge_hash`は、symbol/side/qty/policy_versionが
一致していても「このIntentの元scenarioのものである」ことまでは保証しない
——RiskDecision側のmerge_hashが非空でありさえすれば、別scenarioのPASS済み
RiskDecisionが誤って別Intentへcross-wireされてもlineage checkを通過し
うる穴があった。scripts/execution_contract.pyの`build_intent()`へ必須
非空stringの`merge_hash`を追加（canonical `_HASH_FIELDS`には追加しない）
した上で、`_evaluate_all_gates()`が`intent.merge_hash == risk_decision.
merge_hash`の完全一致を検証し、不一致なら`BLOCK_RISK_LINEAGE_MISMATCH`
でfail closedする。ticketにも一致確認後の値を`merge_hash`として保存し、
`evaluate_reconfirmation()`は現在のIntent・ticket-bound値・現在の
RiskDecisionの3者一致を再確認（`BLOCK_INTENT_MERGE_HASH_MISMATCH`/
`BLOCK_RISK_DECISION_MERGE_HASH_MISMATCH`）してからfingerprintを見る。
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
SCHEMA_VERSION = "execution-permission-1.1"

PERMISSION_STATUSES = ("ORDER_TICKET_READY", "BLOCKED", "EXPIRED_REQUOTE_REQUIRED")
RECONFIRM_STATUSES = ("CONFIRM_READY", "RECONFIRM_REQUIRED", "EXPIRED_REQUOTE_REQUIRED", "BLOCKED")

# v0.1で凍結した安全上限そのもの。ここに書いた数値を緩める変更は、この
# コメントを含むコードレビューを経ずに行わない前提とする。将来緩める場合は
# policy_versionを上げて新しいv0.2検証を別途実装する（risk_gate.pyの
# validate_policy_v0_1と同じ方針）。
EXECUTION_POLICY_VERSION_V0_1 = "execution-safety-0.1.0"
V0_1_MAX_TICKET_AGE_SEC = 15
V0_1_MAX_PRICE_DRIFT_BPS = 50
V0_1_MAX_AUTHORIZATION_TTL_SEC = 3600
V0_1_MAX_MASTER_KILL_TTL_SEC = 3600
V0_1_MAX_DAILY_STOP_YEN = 3000
V0_1_MAX_OPEN_POSITIONS = 1


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
    import math
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_positive_finite_number(value) -> bool:
    return _is_finite_number(value) and value > 0


def _is_positive_integer(value) -> bool:
    return _is_positive_finite_number(value) and int(value) == value


def _in_range_0_exclusive_to(value, upper_inclusive) -> bool:
    return _is_finite_number(value) and 0 < value <= upper_inclusive


def _non_empty_str(value) -> bool:
    return isinstance(value, str) and len(value) > 0


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


def validate_execution_policy_v0_1(policy) -> list[str]:
    """execution safety policyがv0.1の安全境界を満たしているか検証する
    純粋関数（Phase 4.1 Blocker 3）。非dictはBLOCK_POLICY_INVALID_TYPEを
    即座に返し`.get()`を一切呼ばない。安全側への縮小は許可し、上限拡大は
    BLOCKする。違反が無ければ空リストを返す。
    """
    if not isinstance(policy, dict):
        return ["BLOCK_POLICY_INVALID_TYPE"]
    violations = []
    if policy.get("policy_version") != EXECUTION_POLICY_VERSION_V0_1:
        violations.append("BLOCK_POLICY_VERSION_UNSUPPORTED")
    if not _in_range_0_exclusive_to(policy.get("max_ticket_age_sec"), V0_1_MAX_TICKET_AGE_SEC):
        violations.append("BLOCK_POLICY_MAX_TICKET_AGE_OUT_OF_RANGE")
    if not _in_range_0_exclusive_to(policy.get("max_price_drift_bps"), V0_1_MAX_PRICE_DRIFT_BPS):
        violations.append("BLOCK_POLICY_MAX_PRICE_DRIFT_OUT_OF_RANGE")
    if not _in_range_0_exclusive_to(policy.get("authorization_ttl_sec"), V0_1_MAX_AUTHORIZATION_TTL_SEC):
        violations.append("BLOCK_POLICY_AUTHORIZATION_TTL_OUT_OF_RANGE")
    if not _in_range_0_exclusive_to(policy.get("master_kill_ttl_sec"), V0_1_MAX_MASTER_KILL_TTL_SEC):
        violations.append("BLOCK_POLICY_MASTER_KILL_TTL_OUT_OF_RANGE")
    if not _in_range_0_exclusive_to(policy.get("daily_stop_yen"), V0_1_MAX_DAILY_STOP_YEN):
        violations.append("BLOCK_POLICY_DAILY_STOP_OUT_OF_RANGE")
    max_open = policy.get("max_open_positions")
    if not (_is_positive_integer(max_open) and max_open == V0_1_MAX_OPEN_POSITIONS):
        violations.append("BLOCK_POLICY_MAX_OPEN_POSITIONS_OUT_OF_RANGE")
    return violations


def check_master_kill(kill_state: dict, *, now: datetime, policy: dict) -> tuple[bool, list[str]]:
    """master kill switchがARMED・有効期限内・TTL内かを確認する純粋関数。
    デフォルト（default_kill_switch_state()）はDISARMEDなので、呼び出し側が
    明示的にARMED状態を渡さない限り常にBLOCKされる（Phase 4.1: armed_atの
    aware検証とTTL検証を追加）。
    """
    if not isinstance(kill_state, dict) or kill_state.get("status") != "ARMED":
        return False, ["BLOCK_MASTER_KILL_DISARMED"]
    armed_at = _parse_aware(kill_state.get("armed_at"))
    expires_at = _parse_aware(kill_state.get("expires_at"))
    if armed_at is None or expires_at is None:
        return False, ["BLOCK_MASTER_KILL_EXPIRY_INVALID"]
    if not (armed_at <= now < expires_at):
        return False, ["BLOCK_MASTER_KILL_EXPIRED"]
    if (expires_at - armed_at).total_seconds() > policy["master_kill_ttl_sec"]:
        return False, ["BLOCK_MASTER_KILL_TTL_EXCEEDED"]
    return True, []


def check_authorization(snapshot: dict, *, now: datetime, policy: dict) -> tuple[bool, list[str]]:
    """human authorizationがtrue・有効期限内・TTL内かを確認する純粋関数
    （Phase 4.1: authorization_issued_atを追加しTTLを実検証する）。
    """
    reasons = []
    if snapshot.get("human_session_authorized") is not True:
        reasons.append("BLOCK_HUMAN_AUTHORIZATION_MISSING")
    issued_at = _parse_aware(snapshot.get("authorization_issued_at"))
    expires_at = _parse_aware(snapshot.get("authorization_expires_at"))
    if issued_at is None or expires_at is None:
        reasons.append("BLOCK_AUTHORIZATION_EXPIRY_INVALID")
        return (len(reasons) == 0), reasons
    # Phase 4.2 hardening（C-054R-GPT Blocker 2）: issued_atが未来なら、まだ
    # 発行されていないauthorizationを有効扱いしてしまう。またexpires_atが
    # issued_at以下だと、TTL差分が負値になり`> ttl_sec`判定をすり抜けて
    # TTL超過を見逃しうる（負の秒数は`policy["authorization_ttl_sec"]`より
    # 大きくならないため）。両方を明示的に検証する。
    if issued_at > now:
        reasons.append("BLOCK_AUTHORIZATION_ISSUED_AT_FUTURE")
    if expires_at <= issued_at:
        reasons.append("BLOCK_AUTHORIZATION_EXPIRY_BEFORE_ISSUED")
    if expires_at <= now:
        reasons.append("BLOCK_AUTHORIZATION_EXPIRED")
    if (expires_at - issued_at).total_seconds() > policy["authorization_ttl_sec"]:
        reasons.append("BLOCK_AUTHORIZATION_TTL_EXCEEDED")
    return (len(reasons) == 0), reasons


def check_price_drift(*, planned_entry: float, quote_price: float, quote_asof: str,
                       ticket_created_at: str, now: datetime, policy: dict) -> tuple[bool, list[str]]:
    """quoteの鮮度とplanned entryからの価格乖離を確認する。Phase 4の2箇所
    （ticket生成直前・human confirm直前）で同じロジックを呼ぶ（C-053第7節）。
    ticket_created_atは常にIntent自身の`created_at`から渡すこと（呼び出し側
    がsnapshot由来の値で若く見せかけられないようにするのは呼び出し側の責務）。
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
                                allowed_qty: int, intent_created_at: str, signal_known_at: str,
                                quote_price: float, quote_asof: str,
                                authorization_session_id: str, authorization_issued_at: str,
                                authorization_expires_at: str,
                                broker_snapshot_fingerprint: str, permission_policy_version: str) -> str:
    """human confirmationを結び付けるための決定論的fingerprint。canonical
    `intent_hash`とは別物（C-053第9節）。

    Phase 4.2 hardening（C-054R-GPT Blocker 1/2）: `intent_created_at`
    （canonical intent_hashの対象外だがticket ageの安全な基準になる値）・
    `signal_known_at`（同じくhash対象外）・`authorization_issued_at`を
    fingerprintへ含める。これにより、mutableなIntentの`created_at`/
    `signal_known_at`だけを後から書き換えても（canonical hashは変わらない
    ため検出できない）、あるいはauthorizationのissued_atだけ差し替えても、
    fingerprintの不一致として検出できる。
    """
    payload = {
        "intent_hash": intent_hash,
        "merge_hash": merge_hash,
        "risk_policy_version": risk_policy_version,
        "allowed_qty": int(allowed_qty),
        "intent_created_at": intent_created_at,
        "signal_known_at": signal_known_at,
        "quote_price": float(quote_price),
        "quote_asof": quote_asof,
        "authorization_session_id": authorization_session_id,
        "authorization_issued_at": authorization_issued_at,
        "authorization_expires_at": authorization_expires_at,
        "broker_snapshot_fingerprint": broker_snapshot_fingerprint,
        "permission_policy_version": permission_policy_version,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_intent_integrity(intent, *, now: datetime) -> Optional[list[str]]:
    """Intentの型・改ざん・signal_known_atのaware/未来チェック。問題が
    あれば理由リストを返し、無ければNoneを返す（Phase 4.1 Blocker 4）。
    """
    if not isinstance(intent, dict):
        return ["BLOCK_INTENT_INVALID_TYPE"]
    try:
        recomputed = ec.compute_intent_hash(intent)
    except Exception:  # noqa: BLE001 - 壊れたIntentは安全側でBLOCK
        return ["BLOCK_INTENT_MALFORMED"]
    if intent.get("intent_hash") != recomputed:
        return ["BLOCK_INTENT_HASH_TAMPERED"]
    if intent.get("real_submit_allowed") is not False:
        return ["BLOCK_REAL_SUBMIT_ALLOWED_TAMPERED"]
    signal_known_at = _parse_aware(intent.get("signal_known_at"))
    if signal_known_at is None:
        return ["BLOCK_SIGNAL_KNOWN_AT_NOT_TIMEZONE_AWARE"]
    if signal_known_at > now:
        return ["BLOCK_SIGNAL_KNOWN_AT_FUTURE"]
    created_at = _parse_aware(intent.get("created_at"))
    if created_at is None:
        return ["BLOCK_INTENT_CREATED_AT_NOT_TIMEZONE_AWARE"]
    return None


def _validate_snapshot_shape(snapshot) -> Optional[list[str]]:
    """snapshotの型と、known_intents/pending_orders等のlist[dict]性を検証
    する（Phase 4.1 Blocker 4）。問題が無ければNoneを返す。"""
    if not isinstance(snapshot, dict):
        return ["BLOCK_SNAPSHOT_INVALID_TYPE"]
    for key in ("known_intents", "pending_orders"):
        value = snapshot.get(key)
        if value is None or not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
            return [f"BLOCK_{key.upper()}_INVALID"]
    if not _non_empty_str(snapshot.get("authorization_session_id")):
        return ["BLOCK_AUTHORIZATION_SESSION_ID_MISSING"]
    if not _non_empty_str(snapshot.get("broker_snapshot_fingerprint")):
        return ["BLOCK_BROKER_SNAPSHOT_FINGERPRINT_MISSING"]
    return None


def _evaluate_all_gates(intent: dict, risk_decision: dict, snapshot: dict, policy: dict,
                         *, now: datetime) -> list[str]:
    """price drift/fingerprint以外の全ゲートをsnapshotに対して評価し、違反
    理由のリストを返す純粋関数。evaluate_permission()とevaluate_
    reconfirmation()の両方がこの同じcoreを呼ぶ（Phase 4.1 Blocker 2:
    reconfirm直前がticket生成時より弱いチェックにならないようにする）。
    """
    reasons = []

    # --- lineage: RiskDecisionが本当にこのIntentのものか（Blocker 1） -------
    if not isinstance(risk_decision, dict) or risk_decision.get("decision") != "PASS":
        reasons.append("BLOCK_RISK_GATE_NOT_PASS")
    else:
        allowed_qty = risk_decision.get("allowed_qty")
        if not _is_positive_integer(allowed_qty):
            reasons.append("BLOCK_ALLOWED_QTY_INVALID")
        elif intent.get("quantity") != int(allowed_qty):
            reasons.append("BLOCK_RISK_LINEAGE_MISMATCH")
        if risk_decision.get("symbol") != intent.get("symbol"):
            reasons.append("BLOCK_RISK_LINEAGE_MISMATCH")
        if risk_decision.get("side") != intent.get("side"):
            reasons.append("BLOCK_RISK_LINEAGE_MISMATCH")
        if risk_decision.get("policy_version") != intent.get("risk_policy_version"):
            reasons.append("BLOCK_RISK_LINEAGE_MISMATCH")
        if not _non_empty_str(risk_decision.get("merge_hash")):
            reasons.append("BLOCK_MERGE_HASH_INVALID")
        elif intent.get("merge_hash") != risk_decision.get("merge_hash"):
            # Phase 4.3 lineage hardening（C-055R-GPT）: RiskDecisionのmerge_hashが
            # 非空でも、それがこのIntentの元scenarioのものとは限らない。symbol/side/
            # qty/policy_versionが一致していてもmerge_hash不一致ならcross-wireを疑い
            # fail closedする。
            reasons.append("BLOCK_RISK_LINEAGE_MISMATCH")

    if snapshot.get("conflict_state") not in ("PASS", "CANDIDATE_READY"):
        reasons.append("BLOCK_CONFLICT_STATE_NOT_PASS")

    # --- Master Kill ---------------------------------------------------------
    kill_ok, kill_reasons = check_master_kill(snapshot.get("kill_switch", {}), now=now, policy=policy)
    if not kill_ok:
        reasons.extend(kill_reasons)

    # --- Human Authorization --------------------------------------------------
    auth_ok, auth_reasons = check_authorization(snapshot, now=now, policy=policy)
    if not auth_ok:
        reasons.extend(auth_reasons)

    # --- Data freshness / session / tradeability ------------------------------
    if snapshot.get("data_freshness") != "OK":
        reasons.append("BLOCK_DATA_FRESHNESS_NOT_OK")
    if snapshot.get("market_session_allowed") is not True:
        reasons.append("BLOCK_MARKET_SESSION_NOT_ALLOWED")
    if snapshot.get("symbol_tradeable") is not True:
        reasons.append("BLOCK_SYMBOL_NOT_TRADEABLE")
    if snapshot.get("broker_link_health") != "OK":
        reasons.append("BLOCK_BROKER_LINK_UNHEALTHY")

    # --- Position reconciliation / buying power / shortable -------------------
    recon_blocked, recon_reasons = og.check_position_reconciliation(
        snapshot.get("expected_position_qty"), snapshot.get("broker_position_qty"))
    if recon_blocked:
        reasons.extend(recon_reasons)
    if snapshot.get("buying_power_check") is not True:
        reasons.append("BLOCK_BUYING_POWER_NOT_CONFIRMED")
    if intent.get("side") == "SELL" and snapshot.get("short_availability_check") is not True:
        reasons.append("BLOCK_SHORT_AVAILABILITY_NOT_CONFIRMED")

    # --- Daily loss / max positions（Risk Gate通過後もdefense-in-depthで再確認） --
    realized_pnl_today = snapshot.get("realized_pnl_today_yen")
    if not _is_finite_number(realized_pnl_today):
        reasons.append("BLOCK_REALIZED_PNL_UNKNOWN")
    elif max(0.0, -realized_pnl_today) >= policy["daily_stop_yen"]:
        reasons.append("BLOCK_DAILY_STOP_REACHED")
    # Phase 4.2 hardening（C-054R-GPT small hardening節）: open_positions_countは
    # 0以上の整数のみを許可する。finiteなだけでは-1や0.5を通してしまう。
    open_positions_count = snapshot.get("open_positions_count")
    if not _is_finite_number(open_positions_count) or int(open_positions_count) != open_positions_count \
            or open_positions_count < 0:
        reasons.append("BLOCK_OPEN_POSITIONS_COUNT_UNKNOWN")
    elif open_positions_count >= policy["max_open_positions"]:
        reasons.append("BLOCK_MAX_OPEN_POSITIONS_REACHED")

    # --- Duplicate / pending guard ---------------------------------------------
    dup_blocked, dup_reasons = og.is_duplicate_submission(intent["intent_hash"], snapshot["known_intents"])
    if dup_blocked:
        reasons.extend(dup_reasons)
    pending_blocked, pending_reasons = og.check_pending_duplicate(
        intent.get("symbol"), intent.get("side"), snapshot["pending_orders"])
    if pending_blocked:
        reasons.extend(pending_reasons)

    # --- Order fields / tick / lot（外部が精査した結果を受け取るだけ） ---------
    if snapshot.get("price_tick_valid") is not True:
        reasons.append("BLOCK_PRICE_TICK_INVALID")
    if snapshot.get("qty_lot_valid") is not True:
        reasons.append("BLOCK_QTY_LOT_INVALID")

    return reasons


def evaluate_permission(intent: dict, risk_decision: dict, snapshot: dict, policy: dict,
                         *, now: datetime) -> dict:
    """Permission Gateの中核となる純粋関数。ALL-PASS方式——1つでもゲートが
    False/UNKNOWN/missing/staleならBLOCKED。同一入力からは常に同一の
    PermissionDecisionを返す。
    """
    base = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": policy.get("policy_version") if isinstance(policy, dict) else None,
        "generated_at": now.isoformat() if isinstance(now, datetime) and now.tzinfo else None,
        "intent_hash": intent.get("intent_hash") if isinstance(intent, dict) else None,
        "symbol": intent.get("symbol") if isinstance(intent, dict) else None,
        "permission_status": None,
        "ticket_fingerprint": None,
        "block_reasons": [],
    }

    if not isinstance(now, datetime) or now.tzinfo is None:
        return {**base, "permission_status": "BLOCKED", "block_reasons": ["BLOCK_NOW_NOT_TIMEZONE_AWARE"]}

    policy_violations = validate_execution_policy_v0_1(policy)
    if policy_violations:
        return {**base, "permission_status": "BLOCKED", "block_reasons": policy_violations}

    intent_violations = _validate_intent_integrity(intent, now=now)
    if intent_violations:
        return {**base, "permission_status": "BLOCKED", "block_reasons": intent_violations}

    snapshot_violations = _validate_snapshot_shape(snapshot)
    if snapshot_violations:
        return {**base, "permission_status": "BLOCKED", "block_reasons": snapshot_violations}

    # --- Price drift（ticket生成直前のチェックポイント①、最優先で短絡） -------
    # ticket_created_atは必ずIntent自身のcreated_atから取る（snapshot経由の
    # 値でticketを若く見せかけられない、Phase 4.1 Blocker 2）。
    quote_price = snapshot.get("quote_price")
    quote_asof = snapshot.get("quote_asof")
    ticket_created_at = intent.get("created_at")
    planned_entry = intent.get("planned_entry") if intent.get("planned_entry") is not None else intent.get("limit_price")
    drift_ok, drift_reasons = check_price_drift(
        planned_entry=planned_entry, quote_price=quote_price, quote_asof=quote_asof,
        ticket_created_at=ticket_created_at, now=now, policy=policy,
    )
    if not drift_ok:
        return {**base, "permission_status": "EXPIRED_REQUOTE_REQUIRED", "block_reasons": drift_reasons}

    reasons = _evaluate_all_gates(intent, risk_decision, snapshot, policy, now=now)
    if reasons:
        return {**base, "permission_status": "BLOCKED", "block_reasons": sorted(set(reasons))}

    intent_created_at = intent.get("created_at")
    signal_known_at = intent.get("signal_known_at")
    authorization_issued_at = snapshot.get("authorization_issued_at")
    # Phase 4.3 lineage hardening（C-055R-GPT）: _evaluate_all_gates()で
    # intent.merge_hash == risk_decision.merge_hashが既に確認済みなので、
    # ここから先はIntent側の値をticket-boundの単一の正とする（両者が
    # 一致した後の値へ統一し、以後はこれだけを信頼する）。
    merge_hash = intent.get("merge_hash")

    fingerprint = compute_ticket_fingerprint(
        intent_hash=intent["intent_hash"],
        merge_hash=merge_hash,
        risk_policy_version=risk_decision.get("policy_version"),
        allowed_qty=risk_decision.get("allowed_qty"),
        intent_created_at=intent_created_at, signal_known_at=signal_known_at,
        quote_price=quote_price, quote_asof=quote_asof,
        authorization_session_id=snapshot.get("authorization_session_id"),
        authorization_issued_at=authorization_issued_at,
        authorization_expires_at=snapshot.get("authorization_expires_at"),
        broker_snapshot_fingerprint=snapshot.get("broker_snapshot_fingerprint"),
        permission_policy_version=policy.get("policy_version"),
    )
    # Phase 4.2 hardening（C-054R-GPT Blocker 1）: intent_created_at /
    # signal_known_atをticketの安全コンテキストへdeterministicにbindする。
    # reconfirm時はこのticket-bound値だけを信頼し、mutableなIntent側の
    # 現在値でticket ageを若く見せかけられないようにする。Phase 4.3で
    # merge_hashも同じ扱いに揃えた。
    return {
        **base,
        "permission_status": "ORDER_TICKET_READY",
        "ticket_fingerprint": fingerprint,
        "intent_created_at": intent_created_at,
        "signal_known_at": signal_known_at,
        "merge_hash": merge_hash,
    }


def evaluate_reconfirmation(intent: dict, risk_decision: dict, ticket: dict, fresh_snapshot: dict,
                             policy: dict, *, now: datetime) -> dict:
    """human confirmを受け付ける直前のチェックポイント②（C-053第7節・第9節、
    Phase 4.1 Blocker 2）。ticket生成時と同じ全ゲート（`_evaluate_all_gates`）
    をfresh_snapshotに対して再実行してから、price drift/fingerprintを見る
    ——confirm直前がticket生成時より弱いチェックになってはいけない。
    `planned_entry`はIntent自身の値、`ticket_created_at`相当はticket-bound
    値（`ticket["intent_created_at"]`、Phase 4.2）を使い、fresh_snapshot側
    の値でもmutableなIntent側の値でも上書きできない。
    """
    base = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": policy.get("policy_version") if isinstance(policy, dict) else None,
        "generated_at": now.isoformat() if isinstance(now, datetime) and now.tzinfo else None,
        "intent_hash": intent.get("intent_hash") if isinstance(intent, dict) else None,
        "reconfirm_status": None,
        "block_reasons": [],
    }

    if not isinstance(now, datetime) or now.tzinfo is None:
        return {**base, "reconfirm_status": "BLOCKED", "block_reasons": ["BLOCK_NOW_NOT_TIMEZONE_AWARE"]}

    policy_violations = validate_execution_policy_v0_1(policy)
    if policy_violations:
        return {**base, "reconfirm_status": "BLOCKED", "block_reasons": policy_violations}

    intent_violations = _validate_intent_integrity(intent, now=now)
    if intent_violations:
        return {**base, "reconfirm_status": "BLOCKED", "block_reasons": intent_violations}

    if not isinstance(ticket, dict) or ticket.get("permission_status") != "ORDER_TICKET_READY":
        return {**base, "reconfirm_status": "BLOCKED", "block_reasons": ["BLOCK_TICKET_NOT_READY"]}
    if ticket.get("intent_hash") != intent.get("intent_hash"):
        return {**base, "reconfirm_status": "BLOCKED", "block_reasons": ["BLOCK_TICKET_INTENT_MISMATCH"]}

    # Phase 4.2 hardening（C-054R-GPT Blocker 1）: ticket発行時にbindした
    # intent_created_at / signal_known_atと、現在のIntentの値を比較する。
    # canonical intent_hashはこの2フィールドを含まないため、hash一致だけでは
    # mutableなIntentオブジェクト側でcreated_at/signal_known_atだけを後から
    # 書き換える改ざんを検出できない——ここで明示的にBLOCKする。
    binding_reasons = []
    if intent.get("created_at") != ticket.get("intent_created_at"):
        binding_reasons.append("BLOCK_INTENT_CREATED_AT_MISMATCH")
    if intent.get("signal_known_at") != ticket.get("signal_known_at"):
        binding_reasons.append("BLOCK_SIGNAL_KNOWN_AT_MISMATCH")
    # Phase 4.3 lineage hardening（C-055R-GPT）: ticket発行時にbindしたmerge_hashと、
    # 現在のIntent・現在のRiskDecisionそれぞれのmerge_hashの3者一致を再確認する。
    # canonical intent_hashにmerge_hashは含まれないため、ticket発行後にIntent側/
    # RiskDecision側どちらかのmerge_hashだけを別scenarioのものへ差し替えても
    # hash一致検証はすり抜ける——ここで明示的にBLOCKする。
    if intent.get("merge_hash") != ticket.get("merge_hash"):
        binding_reasons.append("BLOCK_INTENT_MERGE_HASH_MISMATCH")
    risk_decision_merge_hash = risk_decision.get("merge_hash") if isinstance(risk_decision, dict) else None
    if risk_decision_merge_hash != ticket.get("merge_hash"):
        binding_reasons.append("BLOCK_RISK_DECISION_MERGE_HASH_MISMATCH")
    if binding_reasons:
        return {**base, "reconfirm_status": "BLOCKED", "block_reasons": sorted(set(binding_reasons))}

    snapshot_violations = _validate_snapshot_shape(fresh_snapshot)
    if snapshot_violations:
        return {**base, "reconfirm_status": "BLOCKED", "block_reasons": snapshot_violations}

    quote_price = fresh_snapshot.get("quote_price")
    quote_asof = fresh_snapshot.get("quote_asof")
    # ticket_created_atはticket-bound値（intent_created_at）のみを正とする。
    # mutableな現在のIntentの`created_at`を直接使うと、fresh_snapshot経由
    # ではなくIntentオブジェクト自体を書き換えてticket ageを若く見せかける
    # 攻撃を防げない（C-054R-GPT Blocker 1の core）。
    ticket_created_at = ticket.get("intent_created_at")
    planned_entry = intent.get("planned_entry") if intent.get("planned_entry") is not None else intent.get("limit_price")
    drift_ok, drift_reasons = check_price_drift(
        planned_entry=planned_entry, quote_price=quote_price, quote_asof=quote_asof,
        ticket_created_at=ticket_created_at, now=now, policy=policy,
    )
    if not drift_ok:
        return {**base, "reconfirm_status": "EXPIRED_REQUOTE_REQUIRED", "block_reasons": drift_reasons}

    reasons = _evaluate_all_gates(intent, risk_decision, fresh_snapshot, policy, now=now)
    if reasons:
        return {**base, "reconfirm_status": "BLOCKED", "block_reasons": sorted(set(reasons))}

    # authorization_issued_atはfresh_snapshot側から都度読み直す——これは
    # 正当な再認証（issued_atの更新）をfingerprint不一致→RECONFIRM_REQUIRED
    # として自然に検出させるためで、intent_created_at/signal_known_atの
    # ticket-bind（上のBlocker 1チェック）とは別の意図（Blocker 2）。
    fresh_fingerprint = compute_ticket_fingerprint(
        intent_hash=intent["intent_hash"],
        merge_hash=ticket.get("merge_hash"),
        risk_policy_version=risk_decision.get("policy_version"),
        allowed_qty=risk_decision.get("allowed_qty"),
        intent_created_at=ticket.get("intent_created_at"), signal_known_at=ticket.get("signal_known_at"),
        quote_price=quote_price, quote_asof=quote_asof,
        authorization_session_id=fresh_snapshot.get("authorization_session_id"),
        authorization_issued_at=fresh_snapshot.get("authorization_issued_at"),
        authorization_expires_at=fresh_snapshot.get("authorization_expires_at"),
        broker_snapshot_fingerprint=fresh_snapshot.get("broker_snapshot_fingerprint"),
        permission_policy_version=policy.get("policy_version"),
    )
    if fresh_fingerprint != ticket.get("ticket_fingerprint"):
        return {**base, "reconfirm_status": "RECONFIRM_REQUIRED", "block_reasons": ["TICKET_FINGERPRINT_CHANGED"]}

    return {**base, "reconfirm_status": "CONFIRM_READY", "block_reasons": []}
