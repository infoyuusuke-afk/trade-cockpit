"""scripts/shadow_forward_acceptance.py

Shadow Forward Acceptance v0.1（GitHub Issue #18 Execution Stack Phase 6、
C-068-GPT comment 5711025033 対応）。

100% Shadow。Real発注への昇格判定は一切行わない。実際のShadow forward
運用で観測されたIntent/Shadow Order/Shadow Positionの記録済み証跡
（呼び出し側が別途privateに永続化したもの）を受け取り、既存の
canonical純粋関数（execution_contract/shadow_execution/shadow_position）
へそのまま再投入した結果（deterministic replay）と記録された最終状態を
突き合わせることで、以下を検証する決定論的・純粋な受入判定エンジン。

- 適格な一意forward intent数が最低50件に達しているか
  （満たなければ`INSUFFICIENT_SAMPLE`——テストデータを捏造して閾値を
  ごまかさない。`INSUFFICIENT_SAMPLE`はコードの欠陥ではない）。
- duplicate submissionが実際に別exposureとして受理されていないか
  （`effective_duplicate_accept_n`は常に0でなければならない）。
- stale/future observationがlifecycle advancement/fillを
  引き起こしていないか。
- 記録されたticket lineageが正当なPermission Gate通過を証明しているか
  （kill/permission bypassの監査）。
- 記録済みinputをdeterministic replayした結果が記録済みの最終状態と
  一致するか。

`SHADOW_FORWARD_REVIEW_ELIGIBLE`は人間のレビューを促すシグナルに過ぎず、
Real発注許可ではない。`REAL_ALLOWED`/`REAL_READY`/`AUTHORIZED_FOR_REAL`
等の自動昇格状態は一切emitしない。RssOrder・Excel注文式・broker
submit/cancel/modify・実ポジション変更は一切実装しない。

## private persistence boundary
実際のforward記録の収集・永続化はこのモジュールの外の責務——Phase 5.0.x/
5.1と同じpure core方針でファイルI/Oを一切行わない。承認済みのprivate
root（呼び出し側が使うべき既にignore済みの場所）:
    data/private/shadow_forward/
    ms2_live/records/
`is_approved_private_path()`はこの境界を検証する純粋ヘルパー。

## forward evidence recordの契約
1件のrecordは以下を持つ:
    source                               "SHADOW_FORWARD"固定（backfill禁止）
    session_date                         JST日付文字列
    intent / risk_decision / ticket      Phase 1-4で生成された生のdict
    submitted_at / submit_now            submit_shadow_order()への入力
    known_shadow_order_ids_at_submission  submit時点で既知だったshadow_order_id一覧
    steps                                [{"type": "ORDER_FILL"|"POSITION_EXIT",
                                            "observation": {...}, "now": <aware dt>}, ...]
    recorded_final_shadow_order_status   forward運用で実際に記録された最終status
    recorded_final_position_status       同上（positionが一度も作られなければNone）
    shadow_order_id / strategy_id / strategy_version / shadow_fill_model_version /
    execution_policy_version / risk_policy_version / ticket_fingerprint / merge_hash
    fill_confidence（診断用、任意）
    source_path（任意、raw evidenceの実際の保存先——private rootの外なら拒否）

## replayについて
記録済みのpoint-in-time inputだけを使い、既存の純粋関数
（`shadow_execution.submit_shadow_order`/`evaluate_shadow_fill`/
`shadow_position.create_shadow_position`/`sync_entry_fill`/
`evaluate_position_exit`）へそのまま再投入する。replayは新しい
forward intentとしてカウントしない——`evaluate_shadow_forward_
acceptance()`を同じ入力で何度呼んでも`eligible_unique_intents`は
変化しない。
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shadow_execution as se
import shadow_fill_model as sfm
import shadow_position as sp

SCHEMA_VERSION = "shadow-forward-acceptance-0.1"

MIN_ELIGIBLE_UNIQUE_INTENTS = 50

STATUSES = ("INSUFFICIENT_SAMPLE", "FAIL_INTEGRITY", "SHADOW_FORWARD_REVIEW_ELIGIBLE")

REQUIRED_SOURCE = "SHADOW_FORWARD"

# 承認済みprivate root（.gitignoreで既にdata/private/・ms2_live/records/を
# 除外済み）。このモジュール自体はここへ書き込まない——境界の検証だけ行う。
APPROVED_PRIVATE_ROOTS = ("data/private/shadow_forward/", "ms2_live/records/")

_REQUIRED_STRING_FIELDS = (
    "session_date", "intent_hash", "shadow_order_id", "strategy_id", "strategy_version",
    "shadow_fill_model_version", "execution_policy_version", "risk_policy_version",
    "ticket_fingerprint", "merge_hash", "recorded_final_shadow_order_status",
)


def is_approved_private_path(path) -> bool:
    """出力/入力pathが承認済みprivate rootの配下かどうかを判定する純粋関数
    （文字列prefix判定、絶対path/parent traversalは拒否）。実際のファイル
    システムには一切アクセスしない。"""
    if not isinstance(path, str) or not path:
        return False
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
        return False
    return any(normalized.startswith(root) for root in APPROVED_PRIVATE_ROOTS)


def _validate_provenance(record) -> list[str]:
    """recordが「実際にforward運用で捕捉された」と主張するに足る最低限の
    provenanceを持っているかをfail-closedで検証する。壊れた/曖昧な
    provenanceは推測補完せずeligible集合から除外する（Golden #12）。"""
    reasons = []
    if not isinstance(record, dict):
        return ["PROVENANCE_INVALID_RECORD_TYPE"]

    if record.get("source") != REQUIRED_SOURCE:
        reasons.append("PROVENANCE_SOURCE_NOT_SHADOW_FORWARD")

    for field in _REQUIRED_STRING_FIELDS:
        value = record.get(field)
        if not isinstance(value, str) or not value:
            reasons.append("PROVENANCE_FIELD_MISSING_" + field.upper())

    for field in ("intent", "risk_decision", "ticket"):
        if not isinstance(record.get(field), dict) or not record.get(field):
            reasons.append("PROVENANCE_FIELD_MISSING_" + field.upper())

    if not isinstance(record.get("steps"), list) or not record.get("steps"):
        reasons.append("PROVENANCE_NO_STEPS")

    submitted_at = record.get("submitted_at")
    if not isinstance(submitted_at, datetime) or submitted_at.tzinfo is None or submitted_at.utcoffset() is None:
        reasons.append("PROVENANCE_SUBMITTED_AT_INVALID")

    submit_now = record.get("submit_now")
    if not isinstance(submit_now, datetime) or submit_now.tzinfo is None or submit_now.utcoffset() is None:
        reasons.append("PROVENANCE_SUBMIT_NOW_INVALID")

    try:
        date.fromisoformat(record.get("session_date", ""))
    except (TypeError, ValueError):
        reasons.append("PROVENANCE_SESSION_DATE_INVALID")

    intent = record.get("intent") if isinstance(record.get("intent"), dict) else {}
    ticket = record.get("ticket") if isinstance(record.get("ticket"), dict) else {}
    crosschecks = {
        "intent_hash": intent.get("intent_hash"),
        "strategy_id": intent.get("strategy_id"),
        "strategy_version": intent.get("strategy_version"),
        "shadow_fill_model_version": intent.get("shadow_fill_model_version"),
        "execution_policy_version": intent.get("execution_policy_version"),
        "risk_policy_version": intent.get("risk_policy_version"),
        "merge_hash": intent.get("merge_hash"),
        "ticket_fingerprint": ticket.get("ticket_fingerprint"),
    }
    for field, canonical in crosschecks.items():
        if record.get(field) != canonical:
            reasons.append("PROVENANCE_MISMATCH_" + field.upper())

    known_ids = record.get("known_shadow_order_ids_at_submission", [])
    if not isinstance(known_ids, list) or not all(isinstance(x, str) for x in known_ids):
        reasons.append("PROVENANCE_KNOWN_ORDER_IDS_INVALID")

    # source_pathの承認済みroot判定は呼び出し側（evaluate_shadow_forward_
    # acceptance()）が専用のprivate_path_leak_nとして独立に数える——ここで
    # 二重にreasonsへ入れるとambiguous_provenance_n側が先にrecordを
    # 除外してしまい、private_path_leak_nが決して増えなくなる。

    return reasons


def _replay_record(record: dict, *, now: datetime) -> dict:
    """1件のrecordが保持するpoint-in-time inputだけを使い、既存のcanonical
    純粋関数へそのまま再投入してreplayする。replayの結果と、record自身が
    主張する`recorded_final_*`との突き合わせは呼び出し側
    （`evaluate_shadow_forward_acceptance()`）の責務——ここではreplay自体
    だけを行い、判定はしない。
    """
    intent = record["intent"]
    known_orders = [{"shadow_order_id": x} for x in record.get("known_shadow_order_ids_at_submission", [])]

    order = se.submit_shadow_order(
        intent, record["risk_decision"], record["ticket"], known_orders=known_orders,
        submitted_at=record["submitted_at"], now=record["submit_now"],
    )

    position = None
    stale_or_future_state_advance = False
    invalid_input_observation_n = 0
    stale_input_n = 0
    future_input_n = 0

    if order.get("status") not in ("REJECTED", "DUPLICATE_IGNORED"):
        for step in record.get("steps", []):
            step_type = step.get("type") if isinstance(step, dict) else None
            step_obs = step.get("observation") if isinstance(step, dict) else None
            step_now = step.get("now") if isinstance(step, dict) else None

            if not isinstance(step_now, datetime) or step_now.tzinfo is None or step_now.utcoffset() is None:
                # 壊れたstepはreplay全体を止めず、chronology整合性違反として扱う。
                stale_or_future_state_advance = True
                continue

            obs_ok, obs_reasons = sfm.validate_observation(step_obs, now=step_now)
            if not obs_ok:
                invalid_input_observation_n += 1
                if "OBSERVATION_FRESHNESS_STALE" in obs_reasons:
                    stale_input_n += 1
                if "OBSERVATION_TIMESTAMP_FUTURE" in obs_reasons:
                    future_input_n += 1

            if step_type == "ORDER_FILL":
                before_filled = order.get("filled_qty")
                order = se.evaluate_shadow_fill(order, step_obs, now=step_now)
                after_filled = order.get("filled_qty")
                if not obs_ok and after_filled != before_filled:
                    stale_or_future_state_advance = True

                if position is None and order.get("status") in ("PARTIAL_FILLED", "FILLED"):
                    position = sp.create_shadow_position(intent, order, now=step_now, known_positions=[])
                elif position is not None:
                    before_entry = position.get("entry_filled_qty_seen")
                    position = sp.sync_entry_fill(position, order, now=step_now)
                    after_entry = position.get("entry_filled_qty_seen")
                    if not obs_ok and after_entry != before_entry:
                        stale_or_future_state_advance = True

            elif step_type == "POSITION_EXIT":
                if position is None:
                    # exit stepの前に一度もentry fillが無い——記録された
                    # イベント順序自体が矛盾している。
                    stale_or_future_state_advance = True
                    continue
                before_status = position.get("status")
                before_qty = position.get("current_qty")
                position = sp.evaluate_position_exit(position, step_obs, now=step_now)
                after_status = position.get("status")
                after_qty = position.get("current_qty")
                if not obs_ok and (after_status != before_status or after_qty != before_qty):
                    stale_or_future_state_advance = True
            else:
                stale_or_future_state_advance = True

    return {
        "replayed_shadow_order_status": order.get("status"),
        "replayed_position_status": position.get("status") if position else None,
        "stale_or_future_state_advance": stale_or_future_state_advance,
        "invalid_input_observation_n": invalid_input_observation_n,
        "stale_input_n": stale_input_n,
        "future_input_n": future_input_n,
    }


def evaluate_shadow_forward_acceptance(records, *, now: datetime) -> dict:
    """記録済みのShadow forward evidence（`records`）を受け取り、Phase 6
    acceptance reportを返す純粋関数。100% Shadow・no hidden wall clock
    （`now`は呼び出し側が明示的に渡す）。50件のsynthetic recordで閾値を
    ごまかすような呼び出し方はこの関数の責務外——ここは渡されたrecordを
    fail-closedに評価するだけで、recordの真正性を保証しない
    （真正性は呼び出し側の収集プロセスの責務）。
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return _early_fail_report(["NOW_NOT_TIMEZONE_AWARE"])
    if not isinstance(records, list):
        return _early_fail_report(["RECORDS_INVALID_TYPE"])

    seen_shadow_order_ids: set[str] = set()
    eligible_records: list[dict] = []

    ambiguous_provenance_n = 0
    duplicate_guard_hit_n = 0
    effective_duplicate_accept_n = 0
    stale_or_future_state_advance_n = 0
    invalid_input_observation_n = 0
    stale_input_n = 0
    future_input_n = 0
    kill_or_permission_bypass_n = 0
    deterministic_replay_mismatch_n = 0
    private_path_leak_n = 0
    integrity_violation = False

    session_dates: set = set()
    strategy_counts: dict[str, int] = {}
    symbol_counts: dict[str, int] = {}
    fill_confidence_counts: dict[str, int] = {}

    for record in records:
        provenance_reasons = _validate_provenance(record)
        if provenance_reasons:
            ambiguous_provenance_n += 1
            continue

        source_path = record.get("source_path")
        if source_path is not None and not is_approved_private_path(source_path):
            private_path_leak_n += 1
            integrity_violation = True
            continue

        intent = record["intent"]
        expected_shadow_order_id = se.compute_shadow_order_id(
            intent.get("intent_hash"), intent.get("shadow_fill_model_version"))
        if record.get("shadow_order_id") != expected_shadow_order_id:
            # recordが主張するshadow_order_idを信用せず、canonical
            # (intent_hash, shadow_fill_model_version)から再導出した値と
            # 一致しなければ、そもそもlineageが曖昧としてeligibleから除外。
            ambiguous_provenance_n += 1
            continue

        replay = _replay_record(record, now=now)
        invalid_input_observation_n += replay["invalid_input_observation_n"]
        stale_input_n += replay["stale_input_n"]
        future_input_n += replay["future_input_n"]
        if replay["stale_or_future_state_advance"]:
            stale_or_future_state_advance_n += 1
            integrity_violation = True

        recorded_order_status = record.get("recorded_final_shadow_order_status")
        recorded_position_status = record.get("recorded_final_position_status")
        replayed_order_status = replay["replayed_shadow_order_status"]
        replayed_position_status = replay["replayed_position_status"]

        if replayed_order_status == "REJECTED" and recorded_order_status != "REJECTED":
            # canonical lineage検証はREJECTEDだと言っているのに、forward
            # 運用側は「受理された」と記録している——permission/kill
            # lineageのbypass。
            kill_or_permission_bypass_n += 1
            integrity_violation = True

        mismatch = (replayed_order_status != recorded_order_status
                    or replayed_position_status != recorded_position_status)
        if mismatch:
            deterministic_replay_mismatch_n += 1
            integrity_violation = True
            continue

        shadow_order_id = record["shadow_order_id"]

        if replayed_order_status == "DUPLICATE_IGNORED":
            # duplicate guardが正しくhitした——診断としては数えるが、
            # 別exposureとしてはeligibleへ加えない（Golden #4）。
            duplicate_guard_hit_n += 1
            continue

        if shadow_order_id in seen_shadow_order_ids:
            # 同一shadow_order_idがguard-hitではない形で2回目「受理」として
            # 現れた——effective duplicate accept（Golden #3/#5）。
            effective_duplicate_accept_n += 1
            integrity_violation = True
            continue

        seen_shadow_order_ids.add(shadow_order_id)
        eligible_records.append(record)
        session_dates.add(record.get("session_date"))
        strategy_key = f"{record.get('strategy_id')}|{record.get('strategy_version')}"
        strategy_counts[strategy_key] = strategy_counts.get(strategy_key, 0) + 1
        symbol = intent.get("symbol")
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
        fc = record.get("fill_confidence")
        fill_confidence_counts[fc] = fill_confidence_counts.get(fc, 0) + 1

    eligible_unique_intents = len(eligible_records)

    if integrity_violation:
        status = "FAIL_INTEGRITY"
    elif eligible_unique_intents < MIN_ELIGIBLE_UNIQUE_INTENTS:
        status = "INSUFFICIENT_SAMPLE"
    else:
        status = "SHADOW_FORWARD_REVIEW_ELIGIBLE"

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "eligible_unique_intents": eligible_unique_intents,
        "min_required": MIN_ELIGIBLE_UNIQUE_INTENTS,
        "ambiguous_provenance_n": ambiguous_provenance_n,
        "duplicate_guard_hit_n": duplicate_guard_hit_n,
        "effective_duplicate_accept_n": effective_duplicate_accept_n,
        "stale_or_future_state_advance_n": stale_or_future_state_advance_n,
        "invalid_input_observation_n": invalid_input_observation_n,
        "stale_input_n": stale_input_n,
        "future_input_n": future_input_n,
        "kill_or_permission_bypass_n": kill_or_permission_bypass_n,
        "deterministic_replay_mismatch_n": deterministic_replay_mismatch_n,
        "private_path_leak_n": private_path_leak_n,
        "unique_session_days": len(session_dates),
        "strategy_distribution": strategy_counts,
        "symbol_distribution": symbol_counts,
        "fill_confidence_distribution": fill_confidence_counts,
        "real_submit_allowed": False,
    }


def _early_fail_report(reasons: list[str]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "FAIL_INTEGRITY",
        "eligible_unique_intents": 0,
        "min_required": MIN_ELIGIBLE_UNIQUE_INTENTS,
        "reject_reasons": sorted(set(reasons)),
        "real_submit_allowed": False,
    }
