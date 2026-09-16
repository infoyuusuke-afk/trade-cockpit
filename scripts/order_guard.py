"""scripts/order_guard.py

Duplicate Order Guard / Position Reconciliation（GitHub Issue #18 Execution
Stack Phase 4、base design C-055 comment 5702335837の第6-7節 + C-053-GPT
comment 5704719373の上書き条件への対応）。

発注は一切行わない。broker/Excel/RSS/networkへ直接取りに行かず、既知の
Intent台帳・broker残高スナップショット等は全て引数として受け取る純粋関数
だけを提供する。

## C-053-GPTによる上書き解釈
- 重複判定はscripts/execution_contract.pyのcanonical `intent_hash`の
  完全一致のみを使う。この関数はhashを再定義・再計算しない。
- `status`の語彙もscripts/execution_contract.pyのINTENT_STATUSESを
  そのまま使う（C-055が使っていた古い独自語彙CONFIRMED/PARTIALLY_FILLED
  /EXPIRED等は使わない——Phase 1で確立したcanonical語彙を優先する）。

## Phase 4.1 hardening（Blocker 5、C-053R-GPT comment 5705124424）
Phase 4当初はREJECTED/CANCELLEDを「新しい試行に道を譲ってよい終端状態」
として同一intent_hashの再利用を許していたが、これはC-055/C-053の
「送信結果や状態が変わったら照合し、新しいIntentでやり直す」という安全
思想と合わないと指摘された。v0.1では**TICKET_READY以降に到達した
intent_hashは、REJECTED/CANCELLEDを含め一切再利用しない**。再試行は
broker reconciliation後、新しいdecision snapshot/Intentとして明示的に
作り直す前提にする。TICKET_READYへ到達する前（CREATED/RISK_BLOCKED/
PERMISSION_BLOCKEDで止まった＝broker側と一切接触していない）場合だけ、
同じhashでの再評価を許可する。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import execution_contract as ec

# TICKET_READY以前（broker/人の確認に一切到達していない）状態だけが
# 「新しい試行に道を譲ってよい」。それ以外は全て同一intent_hashの再利用を
# blockする（UNKNOWNは別理由コードで区別する）。
_PRE_TICKET_STATUSES = frozenset({"CREATED", "RISK_BLOCKED", "PERMISSION_BLOCKED"})


def is_duplicate_submission(intent_hash: str, known_intents: list[dict]) -> tuple[bool, list[str]]:
    """同一intent_hashを持つ既知Intentが、再利用禁止の状態のまま存在するかを
    判定する純粋関数。戻り値は(duplicate_blocked, reasons)。

    known_intents: 各要素が少なくとも{"intent_hash": str, "status": str}を
        持つ辞書のリスト（過去にPermission Gateを通った/通ろうとした
        Intentの台帳。永続化はdata/private/配下の責務でこの関数の外）。
    """
    reasons = []
    for known in known_intents:
        if known.get("intent_hash") != intent_hash:
            continue
        status = known.get("status")
        if status not in ec.INTENT_STATUSES:
            # 壊れた/未知のstatus文字列は安全とみなさない（推測で許可しない）。
            reasons.append("BLOCK_DUPLICATE_MALFORMED_LEDGER_ENTRY")
        elif status == "UNKNOWN":
            reasons.append("BLOCK_DUPLICATE_PENDING_UNKNOWN")
        elif status not in _PRE_TICKET_STATUSES:
            reasons.append("BLOCK_DUPLICATE_INTENT_HASH")
    return (len(reasons) > 0), sorted(set(reasons))


def check_pending_duplicate(symbol: str, side: str, pending_orders: list[dict]) -> tuple[bool, list[str]]:
    """同一symbol・同方向のpending order（intent_hashが違っても）が既に
    存在する場合はblockする（C-055例: pending BUY 100株あり+同一intent
    再到来 → BLOCK_DUPLICATE_PENDING）。
    """
    for pending in pending_orders:
        if pending.get("symbol") == symbol and pending.get("side") == side:
            return True, ["BLOCK_DUPLICATE_PENDING"]
    return False, []


def check_position_reconciliation(expected_position_qty, broker_position_qty) -> tuple[bool, list[str]]:
    """内部で想定しているポジション数量と、broker側の実際の数量が一致するか
    を確認する。不一致なら発注前提が崩れているためblockする（C-055第7節）。
    NaN/None等の未確認値は「一致」とみなさずblockする（推測で一致扱いに
    しない）。
    """
    if not _is_finite_number(expected_position_qty) or not _is_finite_number(broker_position_qty):
        return True, ["BLOCK_POSITION_RECONCILIATION_UNKNOWN"]
    if expected_position_qty != broker_position_qty:
        return True, ["BLOCK_POSITION_RECONCILIATION"]
    return False, []


def _is_finite_number(value) -> bool:
    import math
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
