import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
JST = timezone(timedelta(hours=9))


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ec = _load('ec', 'scripts/execution_contract.py')
ep = _load('ep', 'scripts/execution_permission.py')

NOW = datetime(2026, 9, 17, 9, 0, 0, tzinfo=JST)

POLICY = {
    "policy_version": "execution-safety-0.1.0",
    "max_ticket_age_sec": 15,
    "max_price_drift_bps": 50,
    "authorization_ttl_sec": 3600,
    "master_kill_ttl_sec": 3600,
    "daily_stop_yen": 3000,
    "max_open_positions": 1,
}


def iso(dt: datetime) -> str:
    return dt.isoformat()


def build_intent(**overrides):
    kwargs = dict(
        symbol="285A.T", side="BUY", quantity=100, order_type="LIMIT",
        limit_price=1500.0, planned_entry=1500.0, planned_stop=1450.0, planned_target=1600.0,
        strategy_id="day_ifo_long", strategy_version="1.0",
        decision_snapshot_id="snap-1", signal_known_at="2026-09-17T08:55:00+09:00",
        risk_policy_version="risk-gate-0.1.0", execution_policy_version="exec-v0.1",
        shadow_fill_model_version="shadow-v0.1", merge_hash="m" * 64,
    )
    kwargs.update(overrides)
    intent = ec.build_intent(**kwargs)
    # ec.build_intent()はcreated_atに実行時のdatetime.now(JST)（実際のwall-clock）を
    # 埋め込むため、このテストが使う固定NOWと無関係にずれる。created_atはintent_hashの
    # 対象フィールドではない（execution_contract.pyの_HASH_FIELDS参照）ので、テストの
    # 都合で固定値へ上書きしてもhashの正当性検証には影響しない——CI実行日時に関わらず
    # price drift/ticket age判定を決定論的にするため、ここで固定する。
    intent["created_at"] = iso(NOW - timedelta(seconds=5))
    return intent


def risk_decision(**overrides):
    base = {
        "decision": "PASS", "merge_hash": "m" * 64, "allowed_qty": 100,
        "symbol": "285A.T", "side": "BUY", "horizon": "day",
        "policy_version": "risk-gate-0.1.0",
    }
    base.update(overrides)
    return base


def snapshot(**overrides):
    # kill_switch/authorizationとも、armed_at(issued_at)〜expires_atの幅を
    # policyのTTL上限（3600秒）ちょうどに収める。60秒早くarmed/issueして
    # +3600秒後にexpireさせると幅が3660秒になりTTL超過でBLOCKされてしまう
    # ため、armed_at/issued_atをNOW自身にして幅=3600秒ぴったりにしている。
    base = {
        "kill_switch": {"status": "ARMED", "armed_at": iso(NOW),
                         "expires_at": iso(NOW + timedelta(seconds=3600))},
        "human_session_authorized": True,
        "authorization_issued_at": iso(NOW),
        "authorization_expires_at": iso(NOW + timedelta(seconds=3600)),
        "authorization_session_id": "sess-1",
        "data_freshness": "OK",
        "market_session_allowed": True,
        "symbol_tradeable": True,
        "broker_link_health": "OK",
        "conflict_state": "CANDIDATE_READY",
        "expected_position_qty": 0,
        "broker_position_qty": 0,
        "buying_power_check": True,
        "short_availability_check": True,
        "realized_pnl_today_yen": 0.0,
        "open_positions_count": 0,
        "known_intents": [],
        "pending_orders": [],
        "price_tick_valid": True,
        "qty_lot_valid": True,
        "quote_price": 1500.0,
        "quote_asof": iso(NOW - timedelta(seconds=3)),
        "broker_snapshot_fingerprint": "broker-fp-1",
    }
    base.update(overrides)
    return base


_UNSET = object()


def evaluate(intent=_UNSET, decision=_UNSET, snap=_UNSET, policy=_UNSET, now=NOW):
    # 各引数はNone/[]/""等の意図的なfalsy値をテストで渡すケース（policy=None等）が
    # あるため、「未指定」を表す専用sentinelで判定する（`x if x is not None else ...`
    # や`x or default`はNoneや空値を渡すテストを黙って無効化してしまうバグの元）。
    return ep.evaluate_permission(
        build_intent() if intent is _UNSET else intent,
        risk_decision() if decision is _UNSET else decision,
        snapshot() if snap is _UNSET else snap,
        POLICY if policy is _UNSET else policy,
        now=now,
    )


class HappyPathTests(unittest.TestCase):
    def test_all_gates_pass_gives_order_ticket_ready(self):
        out = evaluate()
        self.assertEqual(out["permission_status"], "ORDER_TICKET_READY")
        self.assertEqual(out["block_reasons"], [])
        self.assertIsNotNone(out["ticket_fingerprint"])


class CanonicalIntentHashTests(unittest.TestCase):
    def test_evaluate_permission_does_not_alter_intent_hash_semantics(self):
        intent = build_intent()
        original_hash = intent["intent_hash"]
        evaluate(intent)
        self.assertEqual(intent["intent_hash"], original_hash)
        self.assertEqual(ec.compute_intent_hash(intent), original_hash)

    def test_tampered_intent_hash_is_blocked(self):
        intent = {**build_intent(), "intent_hash": "0" * 64}
        out = evaluate(intent)
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_INTENT_HASH_TAMPERED", out["block_reasons"])

    def test_tampered_quantity_without_rehash_is_blocked(self):
        intent = {**build_intent(), "quantity": 999}
        out = evaluate(intent)
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_INTENT_HASH_TAMPERED", out["block_reasons"])


class RealSubmitAllowedTests(unittest.TestCase):
    def test_output_never_contains_real_submit_allowed(self):
        self.assertNotIn("real_submit_allowed", evaluate())

    def test_input_intent_real_submit_allowed_stays_false_after_call(self):
        intent = build_intent()
        evaluate(intent)
        self.assertIs(intent["real_submit_allowed"], False)

    def test_tampered_real_submit_allowed_true_is_blocked(self):
        tampered = {**build_intent(), "real_submit_allowed": True}
        out = evaluate(tampered)
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_REAL_SUBMIT_ALLOWED_TAMPERED", out["block_reasons"])


class RiskLineageTests(unittest.TestCase):
    """Phase 4.1 Blocker 1: IntentとRiskDecisionのlineage結合。"""

    def test_golden_1_symbol_mismatch_blocks(self):
        out = evaluate(decision=risk_decision(symbol="8035.T"))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_RISK_LINEAGE_MISMATCH", out["block_reasons"])

    def test_golden_2_side_mismatch_blocks(self):
        out = evaluate(decision=risk_decision(side="SELL"))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_RISK_LINEAGE_MISMATCH", out["block_reasons"])

    def test_golden_3_quantity_not_equal_allowed_qty_blocks(self):
        out = evaluate(decision=risk_decision(allowed_qty=200))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_RISK_LINEAGE_MISMATCH", out["block_reasons"])

    def test_golden_4_risk_policy_version_mismatch_blocks(self):
        out = evaluate(decision=risk_decision(policy_version="risk-gate-9.9.9"))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_RISK_LINEAGE_MISMATCH", out["block_reasons"])

    def test_empty_merge_hash_blocks(self):
        out = evaluate(decision=risk_decision(merge_hash=""))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_MERGE_HASH_INVALID", out["block_reasons"])

    def test_non_positive_allowed_qty_blocks(self):
        for bad_qty in (0, -1, 1.5, float("nan")):
            out = evaluate(decision=risk_decision(allowed_qty=bad_qty))
            self.assertEqual(out["permission_status"], "BLOCKED", msg=f"allowed_qty={bad_qty}")
            self.assertIn("BLOCK_ALLOWED_QTY_INVALID", out["block_reasons"])

    def test_conflict_state_not_pass_blocks(self):
        out = evaluate(snap=snapshot(conflict_state="BLOCKED_DATA_QUALITY"))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_CONFLICT_STATE_NOT_PASS", out["block_reasons"])

    def test_missing_conflict_state_blocks(self):
        out = evaluate(snap=snapshot(conflict_state=None))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_CONFLICT_STATE_NOT_PASS", out["block_reasons"])


class MergeHashLineageTests(unittest.TestCase):
    """Phase 4.3 lineage hardening（C-055R-GPT comment 5707245444）: symbol/side/
    qty/policy_versionが一致していても、merge_hashそのものが一致しなければ
    このIntentの元scenarioのRiskDecisionとは言えない（cross-wire対策）。"""

    def test_golden_1_matching_merge_hash_gives_order_ticket_ready(self):
        out = evaluate()
        self.assertEqual(out["permission_status"], "ORDER_TICKET_READY")
        self.assertEqual(out["merge_hash"], "m" * 64)

    def test_golden_2_same_lineage_fields_but_different_merge_hash_blocks(self):
        """symbol/side/qty/policy_versionは一致するがmerge_hashだけ別scenario
        のものへcross-wireされたケース。"""
        out = evaluate(decision=risk_decision(merge_hash="z" * 64))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_RISK_LINEAGE_MISMATCH", out["block_reasons"])

    def test_golden_3_intent_merge_hash_missing_or_non_string_blocks(self):
        for bad_value in (None, "", 12345):
            tampered = {**build_intent(), "merge_hash": bad_value}
            out = evaluate(tampered)
            self.assertEqual(out["permission_status"], "BLOCKED", msg=f"merge_hash={bad_value!r}")
            self.assertIn("BLOCK_RISK_LINEAGE_MISMATCH", out["block_reasons"])


class MasterKillTests(unittest.TestCase):
    def test_default_kill_switch_state_is_disarmed(self):
        self.assertEqual(ep.default_kill_switch_state()["status"], "DISARMED")

    def test_disarmed_kill_switch_blocks(self):
        out = evaluate(snap=snapshot(kill_switch=ep.default_kill_switch_state()))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_MASTER_KILL_DISARMED", out["block_reasons"])

    def test_golden_12a_naive_armed_at_blocks(self):
        naive = {"status": "ARMED", "armed_at": "2026-09-17T08:59:00",
                  "expires_at": iso(NOW + timedelta(seconds=3600))}
        out = evaluate(snap=snapshot(kill_switch=naive))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_MASTER_KILL_EXPIRY_INVALID", out["block_reasons"])

    def test_golden_12b_future_armed_at_blocks(self):
        future_armed = {"status": "ARMED", "armed_at": iso(NOW + timedelta(seconds=10)),
                         "expires_at": iso(NOW + timedelta(seconds=3600))}
        out = evaluate(snap=snapshot(kill_switch=future_armed))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_MASTER_KILL_EXPIRED", out["block_reasons"])

    def test_golden_12c_ttl_exceeded_blocks(self):
        too_long = {"status": "ARMED", "armed_at": iso(NOW - timedelta(seconds=60)),
                    "expires_at": iso(NOW + timedelta(seconds=7200))}  # TTL=3600s上限を超える
        out = evaluate(snap=snapshot(kill_switch=too_long))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_MASTER_KILL_TTL_EXCEEDED", out["block_reasons"])

    def test_expired_kill_switch_blocks(self):
        expired = {"status": "ARMED", "armed_at": iso(NOW - timedelta(hours=2)),
                   "expires_at": iso(NOW - timedelta(seconds=1))}
        out = evaluate(snap=snapshot(kill_switch=expired))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_MASTER_KILL_EXPIRED", out["block_reasons"])


class AuthorizationTtlTests(unittest.TestCase):
    """Phase 4.1 Golden #13: authorization issued_at/expiry TTL超過 → BLOCK。"""

    def test_expired_authorization_blocks(self):
        out = evaluate(snap=snapshot(authorization_expires_at=iso(NOW - timedelta(seconds=1))))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_AUTHORIZATION_EXPIRED", out["block_reasons"])

    def test_naive_authorization_expiry_blocks(self):
        out = evaluate(snap=snapshot(authorization_expires_at="2026-09-17T10:00:00"))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_AUTHORIZATION_EXPIRY_INVALID", out["block_reasons"])

    def test_naive_authorization_issued_at_blocks(self):
        out = evaluate(snap=snapshot(authorization_issued_at="2026-09-17T08:59:00"))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_AUTHORIZATION_EXPIRY_INVALID", out["block_reasons"])

    def test_authorization_ttl_exceeded_blocks(self):
        out = evaluate(snap=snapshot(
            authorization_issued_at=iso(NOW - timedelta(seconds=60)),
            authorization_expires_at=iso(NOW + timedelta(seconds=7200)),  # 3600s上限超過
        ))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_AUTHORIZATION_TTL_EXCEEDED", out["block_reasons"])

    def test_golden_19_future_authorization_issued_at_blocks(self):
        """Phase 4.2 Blocker 2: まだ発行されていない（未来の）authorizationを
        有効扱いしない。"""
        out = evaluate(snap=snapshot(authorization_issued_at=iso(NOW + timedelta(seconds=10))))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_AUTHORIZATION_ISSUED_AT_FUTURE", out["block_reasons"])

    def test_golden_20_expiry_before_or_equal_issued_at_blocks(self):
        """Phase 4.2 Blocker 2: expires_at<=issued_atだとTTL差分が負値になり
        `> ttl_sec`判定をすり抜けてTTL超過を見逃しうるため、明示的に検証する。"""
        out = evaluate(snap=snapshot(
            authorization_issued_at=iso(NOW),
            authorization_expires_at=iso(NOW - timedelta(seconds=1)),
        ))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_AUTHORIZATION_EXPIRY_BEFORE_ISSUED", out["block_reasons"])

        out2 = evaluate(snap=snapshot(
            authorization_issued_at=iso(NOW),
            authorization_expires_at=iso(NOW),
        ))
        self.assertEqual(out2["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_AUTHORIZATION_EXPIRY_BEFORE_ISSUED", out2["block_reasons"])


class SignalKnownAtTests(unittest.TestCase):
    """Phase 4.1 Golden #14: Intent signal_known_at naive/future → BLOCK。"""

    def test_naive_signal_known_at_blocks(self):
        intent = build_intent(signal_known_at="2026-09-17T08:55:00")
        out = evaluate(intent)
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_SIGNAL_KNOWN_AT_NOT_TIMEZONE_AWARE", out["block_reasons"])

    def test_future_signal_known_at_blocks(self):
        intent = build_intent(signal_known_at=iso(NOW + timedelta(hours=1)))
        out = evaluate(intent)
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_SIGNAL_KNOWN_AT_FUTURE", out["block_reasons"])


class NowTimezoneTests(unittest.TestCase):
    """Phase 4.1 Golden #15: now naive → BLOCK。"""

    def test_naive_now_blocks(self):
        naive_now = datetime(2026, 9, 17, 9, 0, 0)  # tzinfo無し
        out = evaluate(now=naive_now)
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_NOW_NOT_TIMEZONE_AWARE", out["block_reasons"])


class SnapshotShapeTests(unittest.TestCase):
    """Phase 4.1 Golden #16/#17: snapshot・known_intents・pending_orders・
    authorization_session_id・broker_snapshot_fingerprintの検証。"""

    def test_non_dict_snapshot_blocks(self):
        for bad_snap in (None, [], "snapshot"):
            out = evaluate(snap=bad_snap)
            self.assertEqual(out["permission_status"], "BLOCKED", msg=f"snap={bad_snap!r}")

    def test_none_known_intents_blocks(self):
        out = evaluate(snap=snapshot(known_intents=None))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_KNOWN_INTENTS_INVALID", out["block_reasons"])

    def test_malformed_known_intents_element_blocks(self):
        out = evaluate(snap=snapshot(known_intents=["not-a-dict"]))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_KNOWN_INTENTS_INVALID", out["block_reasons"])

    def test_none_pending_orders_blocks(self):
        out = evaluate(snap=snapshot(pending_orders=None))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_PENDING_ORDERS_INVALID", out["block_reasons"])

    def test_missing_authorization_session_id_blocks(self):
        out = evaluate(snap=snapshot(authorization_session_id=""))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_AUTHORIZATION_SESSION_ID_MISSING", out["block_reasons"])

    def test_missing_broker_snapshot_fingerprint_blocks(self):
        out = evaluate(snap=snapshot(broker_snapshot_fingerprint=None))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_BROKER_SNAPSHOT_FINGERPRINT_MISSING", out["block_reasons"])


class ExecutionPolicyEnvelopeTests(unittest.TestCase):
    """Phase 4.1 Blocker 3: execution safety policyのv0.1 envelope。"""

    def test_golden_9_missing_or_unknown_policy_version_blocks(self):
        no_version = {k: v for k, v in POLICY.items() if k != "policy_version"}
        out = evaluate(policy=no_version)
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_POLICY_VERSION_UNSUPPORTED", out["block_reasons"])

        out2 = evaluate(policy={**POLICY, "policy_version": "execution-safety-0.2.0"})
        self.assertEqual(out2["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_POLICY_VERSION_UNSUPPORTED", out2["block_reasons"])

    def test_golden_10_ceilings_cannot_be_widened(self):
        cases = [
            ({**POLICY, "max_ticket_age_sec": 16}, "BLOCK_POLICY_MAX_TICKET_AGE_OUT_OF_RANGE"),
            ({**POLICY, "max_price_drift_bps": 51}, "BLOCK_POLICY_MAX_PRICE_DRIFT_OUT_OF_RANGE"),
            ({**POLICY, "authorization_ttl_sec": 3601}, "BLOCK_POLICY_AUTHORIZATION_TTL_OUT_OF_RANGE"),
            ({**POLICY, "master_kill_ttl_sec": 3601}, "BLOCK_POLICY_MASTER_KILL_TTL_OUT_OF_RANGE"),
            ({**POLICY, "daily_stop_yen": 3001}, "BLOCK_POLICY_DAILY_STOP_OUT_OF_RANGE"),
            ({**POLICY, "max_open_positions": 2}, "BLOCK_POLICY_MAX_OPEN_POSITIONS_OUT_OF_RANGE"),
        ]
        for bad_policy, expected_reason in cases:
            out = evaluate(policy=bad_policy)
            self.assertEqual(out["permission_status"], "BLOCKED", msg=bad_policy)
            self.assertIn(expected_reason, out["block_reasons"])

    def test_golden_11_policy_none_list_or_string_blocks_not_raises(self):
        for bad_policy in (None, [], "execution-safety-0.1.0", 42):
            try:
                out = evaluate(policy=bad_policy)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"evaluate_permission raised {exc!r} for policy={bad_policy!r}")
            self.assertEqual(out["permission_status"], "BLOCKED", msg=f"policy={bad_policy!r}")
            self.assertIn("BLOCK_POLICY_INVALID_TYPE", out["block_reasons"])

    def test_shrinking_within_envelope_still_passes(self):
        shrunk = {**POLICY, "max_ticket_age_sec": 10, "daily_stop_yen": 2000}
        out = evaluate(policy=shrunk)
        self.assertEqual(out["permission_status"], "ORDER_TICKET_READY")

    def test_boundary_values_pass_policy_validation(self):
        self.assertEqual(ep.validate_execution_policy_v0_1(POLICY), [])


class UnknownGateTests(unittest.TestCase):
    def test_missing_human_authorization_blocks(self):
        out = evaluate(snap=snapshot(human_session_authorized=None))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_HUMAN_AUTHORIZATION_MISSING", out["block_reasons"])

    def test_unknown_data_freshness_blocks(self):
        out = evaluate(snap=snapshot(data_freshness="UNKNOWN"))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_DATA_FRESHNESS_NOT_OK", out["block_reasons"])

    def test_unknown_broker_link_health_blocks(self):
        out = evaluate(snap=snapshot(broker_link_health="UNKNOWN"))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_BROKER_LINK_UNHEALTHY", out["block_reasons"])

    def test_missing_buying_power_check_blocks(self):
        out = evaluate(snap=snapshot(buying_power_check=None))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_BUYING_POWER_NOT_CONFIRMED", out["block_reasons"])

    def test_missing_price_tick_or_lot_validity_blocks(self):
        out = evaluate(snap=snapshot(price_tick_valid=None))
        self.assertEqual(out["permission_status"], "BLOCKED")
        out2 = evaluate(snap=snapshot(qty_lot_valid=None))
        self.assertEqual(out2["permission_status"], "BLOCKED")


class PositionReconciliationTests(unittest.TestCase):
    def test_position_mismatch_blocks(self):
        out = evaluate(snap=snapshot(expected_position_qty=0, broker_position_qty=100))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_POSITION_RECONCILIATION", out["block_reasons"])

    def test_short_without_shortable_confirmation_blocks(self):
        sell_intent = build_intent(side="SELL", limit_price=1500.0, planned_entry=1500.0,
                                    planned_stop=1550.0)
        out = evaluate(sell_intent, decision=risk_decision(side="SELL"),
                        snap=snapshot(short_availability_check=None))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_SHORT_AVAILABILITY_NOT_CONFIRMED", out["block_reasons"])


class DailyStopAndMaxPositionsDefenseInDepthTests(unittest.TestCase):
    def test_daily_stop_reached_blocks(self):
        out = evaluate(snap=snapshot(realized_pnl_today_yen=-3000.0))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_DAILY_STOP_REACHED", out["block_reasons"])

    def test_max_open_positions_reached_blocks(self):
        out = evaluate(snap=snapshot(open_positions_count=1))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_MAX_OPEN_POSITIONS_REACHED", out["block_reasons"])

    def test_golden_21_negative_open_positions_count_blocks(self):
        """Phase 4.2 small hardening: open_positions_countは0以上の整数のみ
        許可する。finiteなだけでは-1を通してしまう。"""
        out = evaluate(snap=snapshot(open_positions_count=-1))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_OPEN_POSITIONS_COUNT_UNKNOWN", out["block_reasons"])

    def test_golden_22_fractional_open_positions_count_blocks(self):
        out = evaluate(snap=snapshot(open_positions_count=0.5))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_OPEN_POSITIONS_COUNT_UNKNOWN", out["block_reasons"])


class DuplicateGuardTests(unittest.TestCase):
    def test_duplicate_exact_intent_hash_blocks(self):
        intent = build_intent()
        known = [{"intent_hash": intent["intent_hash"], "status": "TICKET_READY"}]
        out = evaluate(intent, snap=snapshot(known_intents=known))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_DUPLICATE_INTENT_HASH", out["block_reasons"])

    def test_pending_unknown_intent_blocks_no_auto_retry(self):
        intent = build_intent()
        known = [{"intent_hash": intent["intent_hash"], "status": "UNKNOWN"}]
        out = evaluate(intent, snap=snapshot(known_intents=known))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_DUPLICATE_PENDING_UNKNOWN", out["block_reasons"])

    def test_golden_18_rejected_or_cancelled_ticket_cannot_be_reused(self):
        """Phase 4.1 Blocker 5: TICKET_READY以降に到達したintent_hashは
        REJECTED/CANCELLEDを含め再利用しない。"""
        intent = build_intent()
        for status in ("REJECTED", "CANCELLED"):
            known = [{"intent_hash": intent["intent_hash"], "status": status}]
            out = evaluate(intent, snap=snapshot(known_intents=known))
            self.assertEqual(out["permission_status"], "BLOCKED", msg=status)
            self.assertIn("BLOCK_DUPLICATE_INTENT_HASH", out["block_reasons"])

    def test_pre_ticket_status_does_not_block_reuse(self):
        intent = build_intent()
        known = [{"intent_hash": intent["intent_hash"], "status": "RISK_BLOCKED"}]
        out = evaluate(intent, snap=snapshot(known_intents=known))
        self.assertEqual(out["permission_status"], "ORDER_TICKET_READY")

    def test_pending_order_same_symbol_side_blocks(self):
        pending = [{"symbol": "285A.T", "side": "BUY", "qty": 100}]
        out = evaluate(snap=snapshot(pending_orders=pending))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_DUPLICATE_PENDING", out["block_reasons"])


class PriceDriftTests(unittest.TestCase):
    def test_stale_quote_requires_requote(self):
        out = evaluate(snap=snapshot(quote_asof=iso(NOW - timedelta(seconds=60))))
        self.assertEqual(out["permission_status"], "EXPIRED_REQUOTE_REQUIRED")
        self.assertIn("EXPIRED_QUOTE_STALE", out["block_reasons"])

    def test_stale_ticket_requires_requote(self):
        """intent自身のcreated_atが古い場合（例えば実際にIntentが作られてから
        時間が経ってしまった場合）にrequoteが必要になることを確認する。"""
        old_intent = build_intent()
        old_intent = {**old_intent, "created_at": iso(NOW - timedelta(seconds=60))}
        # created_atを直接書き換えるとintent_hashの対象フィールドではないため
        # tamper検知には引っかからない（hash対象はexecution_contract.py参照）。
        out = evaluate(old_intent)
        self.assertEqual(out["permission_status"], "EXPIRED_REQUOTE_REQUIRED")
        self.assertIn("EXPIRED_TICKET_AGE", out["block_reasons"])

    def test_price_drift_beyond_threshold_requires_requote(self):
        drifted_quote = 1500.0 * 1.01
        out = evaluate(snap=snapshot(quote_price=drifted_quote))
        self.assertEqual(out["permission_status"], "EXPIRED_REQUOTE_REQUIRED")
        self.assertIn("EXPIRED_PRICE_DRIFT", out["block_reasons"])

    def test_small_drift_within_threshold_still_passes(self):
        tiny_drift_quote = 1500.0 * 1.001
        out = evaluate(snap=snapshot(quote_price=tiny_drift_quote))
        self.assertEqual(out["permission_status"], "ORDER_TICKET_READY")

    def test_naive_quote_asof_blocks(self):
        out = evaluate(snap=snapshot(quote_asof="2026-09-17T08:59:57"))
        self.assertEqual(out["permission_status"], "EXPIRED_REQUOTE_REQUIRED")
        self.assertIn("BLOCK_TIMESTAMP_NOT_TIMEZONE_AWARE", out["block_reasons"])


class ReconfirmationTests(unittest.TestCase):
    """人の確認直前のチェックポイント②（C-053第7節・第9節、Phase 4.1 Blocker 2）。"""

    def _fresh_snapshot(self, **overrides):
        # snapshot()のkill_switch/authorizationデフォルトが既にTTL上限
        # ぴったりに調整済みなので、ここで別の値へ上書きする必要は無い
        # （以前はarmed_at=NOW-60sで独自に上書きしており、expires_atとの
        # 幅が3660秒になりTTL上限3600秒を超えて誤ってBLOCKされていた）。
        base = snapshot()
        base.update({"quote_price": 1500.0, "quote_asof": iso(NOW - timedelta(seconds=3))})
        base.update(overrides)
        return base

    def _ready_ticket(self):
        intent = build_intent()
        decision = risk_decision()
        ticket = evaluate(intent, decision)
        self.assertEqual(ticket["permission_status"], "ORDER_TICKET_READY")
        return intent, decision, ticket

    def test_unchanged_snapshot_gives_confirm_ready(self):
        intent, decision, ticket = self._ready_ticket()
        out = ep.evaluate_reconfirmation(intent, decision, ticket, self._fresh_snapshot(),
                                          POLICY, now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "CONFIRM_READY")

    def test_price_drift_before_confirm_requires_requote(self):
        intent, decision, ticket = self._ready_ticket()
        drifted = self._fresh_snapshot(quote_price=1500.0 * 1.01)
        out = ep.evaluate_reconfirmation(intent, decision, ticket, drifted, POLICY,
                                          now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "EXPIRED_REQUOTE_REQUIRED")

    def test_fingerprint_change_requires_reconfirm(self):
        intent, decision, ticket = self._ready_ticket()
        changed = self._fresh_snapshot(broker_snapshot_fingerprint="broker-fp-DIFFERENT")
        out = ep.evaluate_reconfirmation(intent, decision, ticket, changed, POLICY,
                                          now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "RECONFIRM_REQUIRED")
        self.assertIn("TICKET_FINGERPRINT_CHANGED", out["block_reasons"])

    def test_new_quote_observation_requires_reconfirm(self):
        intent, decision, ticket = self._ready_ticket()
        refetched = self._fresh_snapshot(quote_asof=iso(NOW - timedelta(seconds=1)))
        out = ep.evaluate_reconfirmation(intent, decision, ticket, refetched, POLICY,
                                          now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "RECONFIRM_REQUIRED")

    def test_ticket_not_ready_blocks_reconfirmation(self):
        intent = build_intent()
        blocked_ticket = evaluate(intent, snap=snapshot(human_session_authorized=None))
        out = ep.evaluate_reconfirmation(intent, risk_decision(), blocked_ticket,
                                          self._fresh_snapshot(), POLICY, now=NOW)
        self.assertEqual(out["reconfirm_status"], "BLOCKED")
        self.assertIn("BLOCK_TICKET_NOT_READY", out["block_reasons"])

    # --- Golden #5/#6/#7: ticket ready後に状態が悪化したらreconfirmでBLOCK ---
    def test_golden_5_kill_disarmed_after_ticket_ready_blocks_reconfirm(self):
        intent, decision, ticket = self._ready_ticket()
        disarmed = self._fresh_snapshot(kill_switch=ep.default_kill_switch_state())
        out = ep.evaluate_reconfirmation(intent, decision, ticket, disarmed, POLICY,
                                          now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "BLOCKED")
        self.assertIn("BLOCK_MASTER_KILL_DISARMED", out["block_reasons"])

    def test_golden_6_daily_stop_reached_after_ticket_ready_blocks_reconfirm(self):
        intent, decision, ticket = self._ready_ticket()
        stopped = self._fresh_snapshot(realized_pnl_today_yen=-3000.0)
        out = ep.evaluate_reconfirmation(intent, decision, ticket, stopped, POLICY,
                                          now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "BLOCKED")
        self.assertIn("BLOCK_DAILY_STOP_REACHED", out["block_reasons"])

    def test_golden_7a_position_mismatch_after_ticket_ready_blocks_reconfirm(self):
        intent, decision, ticket = self._ready_ticket()
        mismatched = self._fresh_snapshot(broker_position_qty=100)
        out = ep.evaluate_reconfirmation(intent, decision, ticket, mismatched, POLICY,
                                          now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "BLOCKED")
        self.assertIn("BLOCK_POSITION_RECONCILIATION", out["block_reasons"])

    def test_golden_7b_broker_unhealthy_after_ticket_ready_blocks_reconfirm(self):
        intent, decision, ticket = self._ready_ticket()
        unhealthy = self._fresh_snapshot(broker_link_health="DOWN")
        out = ep.evaluate_reconfirmation(intent, decision, ticket, unhealthy, POLICY,
                                          now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "BLOCKED")
        self.assertIn("BLOCK_BROKER_LINK_UNHEALTHY", out["block_reasons"])

    def test_golden_7c_duplicate_emerges_after_ticket_ready_blocks_reconfirm(self):
        intent, decision, ticket = self._ready_ticket()
        now_duplicated = self._fresh_snapshot(
            known_intents=[{"intent_hash": intent["intent_hash"], "status": "TICKET_READY"}])
        out = ep.evaluate_reconfirmation(intent, decision, ticket, now_duplicated, POLICY,
                                          now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "BLOCKED")
        self.assertIn("BLOCK_DUPLICATE_INTENT_HASH", out["block_reasons"])

    def test_golden_8_fresh_snapshot_cannot_override_planned_entry_or_ticket_age(self):
        """fresh_snapshotにplanned_entryやticket_created_at相当のキーを
        紛れ込ませても、Intent自身の値（planned_entry/created_at）だけが
        使われ、安全基準を上書きできないことを確認する。"""
        intent, decision, ticket = self._ready_ticket()
        spoofed = self._fresh_snapshot()
        # fresh_snapshotにそれらしいキーを混入させても無視されるはず
        spoofed["planned_entry"] = 999999.0
        spoofed["ticket_created_at"] = iso(NOW)  # 「作られたばかり」に見せかけようとする
        out = ep.evaluate_reconfirmation(intent, decision, ticket, spoofed, POLICY,
                                          now=NOW + timedelta(seconds=2))
        # planned_entry(1500)とquote_price(1500)で乖離ゼロのまま評価されるはず
        # （999999.0が使われていたら巨大なdriftでEXPIRED_REQUOTE_REQUIREDになる）
        self.assertEqual(out["reconfirm_status"], "CONFIRM_READY")

    # --- Phase 4.2 Golden: intent_created_at/signal_known_atのticket-bind ---
    def test_golden_23_intent_created_at_tamper_after_ticket_ready_blocks_reconfirm(self):
        """ticket発行後にIntentオブジェクトのcreated_atだけを書き換えても
        （created_atはintent_hashの対象フィールドではないためhash検証は
        すり抜ける）、ticket-bound値との不一致でBLOCKされることを確認する
        （C-054R-GPT Blocker 1）。"""
        intent, decision, ticket = self._ready_ticket()
        tampered_intent = {**intent, "created_at": iso(NOW)}  # ticketより若く見せかける
        out = ep.evaluate_reconfirmation(tampered_intent, decision, ticket, self._fresh_snapshot(),
                                          POLICY, now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "BLOCKED")
        self.assertIn("BLOCK_INTENT_CREATED_AT_MISMATCH", out["block_reasons"])

    def test_golden_24_signal_known_at_mismatch_after_ticket_ready_blocks_reconfirm(self):
        intent, decision, ticket = self._ready_ticket()
        tampered_intent = {**intent, "signal_known_at": iso(NOW - timedelta(minutes=1))}
        out = ep.evaluate_reconfirmation(tampered_intent, decision, ticket, self._fresh_snapshot(),
                                          POLICY, now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "BLOCKED")
        self.assertIn("BLOCK_SIGNAL_KNOWN_AT_MISMATCH", out["block_reasons"])

    def test_golden_25_authorization_reissued_after_ticket_ready_requires_reconfirm(self):
        """正当な再認証（authorization_issued_atの更新）はintent_created_at/
        signal_known_atのtamperとは別物——fingerprint不一致による
        RECONFIRM_REQUIREDとして検出され、BLOCKにはならない（C-054R-GPT
        Blocker 2）。"""
        intent, decision, ticket = self._ready_ticket()
        reauthorized = self._fresh_snapshot(
            authorization_issued_at=iso(NOW + timedelta(seconds=1)),
            authorization_expires_at=iso(NOW + timedelta(seconds=3601)),
        )
        out = ep.evaluate_reconfirmation(intent, decision, ticket, reauthorized, POLICY,
                                          now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "RECONFIRM_REQUIRED")
        self.assertIn("TICKET_FINGERPRINT_CHANGED", out["block_reasons"])

    def test_ticket_stores_intent_created_at_and_signal_known_at(self):
        intent, decision, ticket = self._ready_ticket()
        self.assertEqual(ticket["intent_created_at"], intent["created_at"])
        self.assertEqual(ticket["signal_known_at"], intent["signal_known_at"])

    # --- Phase 4.3 lineage hardening（C-055R-GPT）: merge_hashの3者bind ---
    def test_golden_26_intent_merge_hash_tamper_after_ticket_ready_blocks_reconfirm(self):
        """Golden #4: ticket発行後にIntentオブジェクトのmerge_hashだけ書き換え
        ても（merge_hashはintent_hashの対象フィールドではないためhash検証は
        すり抜ける）、ticket-bound値との不一致でBLOCKされることを確認する。"""
        intent, decision, ticket = self._ready_ticket()
        tampered_intent = {**intent, "merge_hash": "z" * 64}
        out = ep.evaluate_reconfirmation(tampered_intent, decision, ticket, self._fresh_snapshot(),
                                          POLICY, now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "BLOCKED")
        self.assertIn("BLOCK_INTENT_MERGE_HASH_MISMATCH", out["block_reasons"])

    def test_golden_27_risk_decision_merge_hash_tamper_after_ticket_ready_blocks_reconfirm(self):
        """Golden #5: ticket発行後にRiskDecision側のmerge_hashだけ差し替え
        られた場合もBLOCK。"""
        intent, decision, ticket = self._ready_ticket()
        tampered_decision = {**decision, "merge_hash": "z" * 64}
        out = ep.evaluate_reconfirmation(intent, tampered_decision, ticket, self._fresh_snapshot(),
                                          POLICY, now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "BLOCKED")
        self.assertIn("BLOCK_RISK_DECISION_MERGE_HASH_MISMATCH", out["block_reasons"])

    def test_ticket_stores_merge_hash(self):
        intent, decision, ticket = self._ready_ticket()
        self.assertEqual(ticket["merge_hash"], intent["merge_hash"])
        self.assertEqual(ticket["merge_hash"], decision["merge_hash"])


class DeterminismTests(unittest.TestCase):
    def test_same_input_gives_same_decision(self):
        out_a = evaluate()
        out_b = evaluate()
        self.assertEqual(out_a, out_b)  # nowを固定して渡しているのでgenerated_atも完全一致するはず


class NoBrokerReferenceTests(unittest.TestCase):
    def test_execution_permission_has_no_broker_rss_or_network_references(self):
        self._assert_clean(ROOT / "scripts/execution_permission.py")

    def _assert_clean(self, path):
        import ast
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden_names = {"RssOrder", "win32com", "pywin32", "xlwings", "openpyxl"}
        forbidden_modules = {"win32com", "requests", "urllib", "socket", "http", "xlwings", "openpyxl"}
        found = set()
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden_names:
                found.add(node.id)
            elif isinstance(node, ast.Attribute) and node.attr in forbidden_names:
                found.add(node.attr)
            elif isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(found, set())
        self.assertEqual(imported & forbidden_modules, set())

    def test_collector_still_has_no_order_submit_path(self):
        collector = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
        source = collector.read_text(encoding="utf-8")
        self.assertNotIn("RssOrder", source)
        self.assertIn("$AutoOrderEnabled = $false", source)


if __name__ == "__main__":
    unittest.main()
