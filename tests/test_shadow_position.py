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
se = _load('se', 'scripts/shadow_execution.py')
sp = _load('sp', 'scripts/shadow_position.py')

NOW = datetime(2026, 9, 17, 9, 0, 0, tzinfo=JST)
SUBMITTED_AT = NOW - timedelta(seconds=10)


def build_intent(**overrides):
    kwargs = dict(
        symbol="285A.T", side="BUY", quantity=100, order_type="LIMIT",
        limit_price=1500.0, planned_entry=1500.0, planned_stop=1450.0, planned_target=1600.0,
        strategy_id="day_ifo_long", strategy_version="1.0",
        decision_snapshot_id="snap-1", signal_known_at="2026-09-17T08:55:00+09:00",
        risk_policy_version="risk-gate-0.1.0", execution_policy_version="exec-v0.1",
        shadow_fill_model_version="shadow-fill-model-0.1", merge_hash="m" * 64,
    )
    kwargs.update(overrides)
    return ec.build_intent(**kwargs)


def entry_intent(**overrides):
    kwargs = dict(order_type="MARKET", limit_price=None)
    kwargs.update(overrides)
    return build_intent(**kwargs)


def risk_decision(**overrides):
    base = {
        "decision": "PASS", "merge_hash": "m" * 64, "allowed_qty": 100,
        "symbol": "285A.T", "side": "BUY", "policy_version": "risk-gate-0.1.0",
    }
    base.update(overrides)
    return base


def ticket(intent, **overrides):
    base = {
        "permission_status": "ORDER_TICKET_READY",
        "intent_hash": intent["intent_hash"],
        "merge_hash": intent["merge_hash"],
        "ticket_fingerprint": "fp-" + "a" * 60,
    }
    base.update(overrides)
    return base


def observation(**overrides):
    base = {
        "observed_at": NOW,
        "bid": 1499.0, "ask": 1500.0,
        "bid_qty": 500, "ask_qty": 500,
        "last_trade_price": 1500.0, "last_trade_qty": 100,
        "tick_size": 1.0,
        "data_freshness": "OK",
    }
    base.update(overrides)
    return base


def submit(intent, decision, tkt, *, known_orders=None, submitted_at=SUBMITTED_AT, now=NOW):
    return se.submit_shadow_order(intent, decision, tkt, known_orders=[] if known_orders is None else known_orders,
                                   submitted_at=submitted_at, now=now)


def filled_order(intent, **obs_overrides):
    """entry_intent()から生成したShadow Orderへ1回のobservationを適用し、
    Shadow Positionテストの入力として使うfilled/partial-filledなShadow
    Orderを作るテストヘルパー。observed_at/decisionはtest_shadow_execution.py
    と同じ規約（NOW, PASS/ORDER_TICKET_READY）を踏襲する。"""
    order = submit(intent, risk_decision(), ticket(intent))
    return se.evaluate_shadow_fill(order, observation(**obs_overrides), now=NOW)


class Golden1ZeroFillTests(unittest.TestCase):
    def test_golden_1_new_zero_fill_order_cannot_create_position(self):
        intent = entry_intent()
        order = submit(intent, risk_decision(), ticket(intent))
        self.assertEqual(order["status"], "NEW")
        out = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_SHADOW_ORDER_NOT_POSITIVE_FILL", out["reject_reasons"])

    def test_golden_1_working_zero_fill_order_cannot_create_position(self):
        intent = entry_intent()
        order = {**submit(intent, risk_decision(), ticket(intent)), "status": "WORKING"}
        out = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_SHADOW_ORDER_NOT_POSITIVE_FILL", out["reject_reasons"])


class Golden2CreateOpenPositionTests(unittest.TestCase):
    def test_golden_2_first_partial_fill_creates_open_position_at_first_fill_at(self):
        intent = entry_intent()
        order = filled_order(intent, ask_qty=40)
        self.assertEqual(order["status"], "PARTIAL_FILLED")
        out = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        self.assertEqual(out["status"], "OPEN")
        self.assertEqual(out["position_opened_at"], order["first_fill_at"])
        self.assertEqual(out["current_qty"], 40)
        self.assertEqual(out["entry_filled_qty_seen"], 40)
        self.assertEqual(out["avg_entry_price"], order["avg_fill_price"])

    def test_golden_2_duplicate_shadow_order_id_gives_duplicate_ignored(self):
        intent = entry_intent()
        order = filled_order(intent, ask_qty=40)
        first = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        second = sp.create_shadow_position(intent, order, now=NOW, known_positions=[first])
        self.assertEqual(second["status"], "DUPLICATE_IGNORED")
        self.assertEqual(second["position_id"], first["position_id"])

    def test_known_positions_invalid_type_rejected(self):
        intent = entry_intent()
        order = filled_order(intent, ask_qty=40)
        out = sp.create_shadow_position(intent, order, now=NOW, known_positions="not-a-list")
        self.assertEqual(out["status"], "REJECTED")


class Golden3EntryGrowthTests(unittest.TestCase):
    def test_golden_3_later_entry_fill_increases_qty_without_reopening(self):
        intent = entry_intent()
        order1 = filled_order(intent, ask_qty=40)
        pos = sp.create_shadow_position(intent, order1, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        order2 = se.evaluate_shadow_fill(order1, observation(observed_at=later, ask_qty=60), now=later)
        self.assertEqual(order2["status"], "FILLED")
        synced = sp.sync_entry_fill(pos, order2, now=later)
        self.assertEqual(synced["status"], "OPEN")
        self.assertEqual(synced["current_qty"], 100)
        self.assertEqual(synced["entry_filled_qty_seen"], 100)
        self.assertEqual(synced["remaining_position_qty"], 100)
        self.assertEqual(synced["last_entry_fill_at"], later)

    def test_unchanged_fill_is_a_no_op(self):
        intent = entry_intent()
        order = filled_order(intent, ask_qty=40)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        synced = sp.sync_entry_fill(pos, order, now=NOW)
        self.assertEqual(synced["current_qty"], 40)
        self.assertEqual(synced["entry_sync_reasons"], [])


class Golden4RollbackIdentityTests(unittest.TestCase):
    def test_golden_4_entry_fill_rollback_rejected(self):
        intent = entry_intent()
        order = filled_order(intent, ask_qty=40)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        rolled_back = {**order, "filled_qty": 10, "remaining_qty": 90}
        out = sp.sync_entry_fill(pos, rolled_back, now=NOW)
        self.assertIn("REJECTED_ENTRY_QTY_ROLLBACK", out["entry_sync_reasons"])
        self.assertEqual(out["current_qty"], 40)

    def test_golden_4_identity_mismatch_rejected(self):
        intent = entry_intent()
        order = filled_order(intent, ask_qty=40)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        other_order = {**order, "shadow_order_id": "z" * 64}
        out = sp.sync_entry_fill(pos, other_order, now=NOW)
        self.assertIn("REJECTED_SHADOW_ORDER_IDENTITY_MISMATCH", out["entry_sync_reasons"])
        self.assertEqual(out["current_qty"], 40)


class Golden5IntentHashTamperTests(unittest.TestCase):
    def test_golden_5_intent_hash_tamper_rejected(self):
        intent = entry_intent()
        order = filled_order(intent)
        tampered_intent = {**intent, "intent_hash": "0" * 64}
        out = sp.create_shadow_position(tampered_intent, order, now=NOW, known_positions=[])
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_INTENT_HASH_TAMPERED", out["reject_reasons"])


class Golden6MissingFingerprintTests(unittest.TestCase):
    def test_golden_6_missing_ticket_fingerprint_rejected(self):
        intent = entry_intent()
        order = filled_order(intent)
        bad_order = {**order, "ticket_fingerprint": ""}
        out = sp.create_shadow_position(intent, bad_order, now=NOW, known_positions=[])
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_TICKET_FINGERPRINT_MISSING", out["reject_reasons"])

    def test_golden_6_invalid_order_context_fingerprint_rejected(self):
        intent = entry_intent()
        order = filled_order(intent)
        bad_order = {**order, "order_context_fingerprint": ""}
        out = sp.create_shadow_position(intent, bad_order, now=NOW, known_positions=[])
        self.assertEqual(out["status"], "REJECTED")


class Golden7PlanFingerprintTests(unittest.TestCase):
    def test_golden_7_planned_target_mutation_detected(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        tampered = {**pos, "planned_target": 9999.0}
        reasons = sp._validate_position_state(tampered, now=NOW)
        self.assertIn("REJECTED_POSITION_PLAN_MISMATCH", reasons)

    def test_golden_7_untampered_position_passes_state_validation(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        reasons = sp._validate_position_state(pos, now=NOW)
        self.assertEqual(reasons, [])


class Golden8DirectionTests(unittest.TestCase):
    def test_golden_8_wrong_direction_stop_rejected(self):
        intent = entry_intent(planned_stop=1550.0)
        order = filled_order(intent)
        out = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_PLANNED_STOP_WRONG_DIRECTION", out["reject_reasons"])

    def test_golden_8_wrong_direction_target_rejected(self):
        intent = entry_intent(planned_target=1400.0)
        order = filled_order(intent)
        out = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_PLANNED_TARGET_WRONG_DIRECTION", out["reject_reasons"])

    def test_golden_8_planned_target_none_allowed(self):
        intent = entry_intent(planned_target=None)
        order = filled_order(intent)
        out = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        self.assertEqual(out["status"], "OPEN")
        self.assertIsNone(out["planned_target"])


class Golden9TargetTradeThroughTests(unittest.TestCase):
    def test_golden_9_target_trade_through_closes(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        obs = observation(observed_at=later, last_trade_price=1601.0)
        out = sp.evaluate_position_exit(pos, obs, now=later)
        self.assertEqual(out["status"], "CLOSED")
        self.assertEqual(out["exit_reason"], "TARGET")
        self.assertEqual(out["avg_exit_price"], 1600.0)
        self.assertEqual(out["exit_filled_qty"], 100)
        self.assertEqual(out["remaining_position_qty"], 0)

    def test_golden_9_target_touch_only_does_not_close(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        obs = observation(observed_at=later, last_trade_price=1600.0)
        out = sp.evaluate_position_exit(pos, obs, now=later)
        self.assertEqual(out["status"], "OPEN")
        self.assertEqual(out["fill_reason"], "TOUCH_ONLY")


class Golden10QuoteOnlyTests(unittest.TestCase):
    def test_golden_10_quote_only_touch_without_trade_does_not_close(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        obs = observation(observed_at=later, bid=1600.0, ask=1601.0, last_trade_price=1550.0)
        out = sp.evaluate_position_exit(pos, obs, now=later)
        self.assertEqual(out["status"], "OPEN")


class Golden11StopTriggerNoFillTests(unittest.TestCase):
    def test_golden_11_stop_trigger_no_fill_same_observation(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        obs = observation(observed_at=later, last_trade_price=1440.0, bid=1439.0, ask=1440.0)
        out = sp.evaluate_position_exit(pos, obs, now=later)
        self.assertEqual(out["status"], "STOP_TRIGGERED")
        self.assertEqual(out["stop_triggered_at"], later)
        self.assertEqual(out["current_qty"], 100)
        self.assertEqual(out["exit_filled_qty"], 0)


class Golden12NextObservationFillsTests(unittest.TestCase):
    def test_golden_12_next_observation_fills_long_stop_at_bid(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        triggered = sp.evaluate_position_exit(
            pos, observation(observed_at=later, last_trade_price=1440.0), now=later)
        self.assertEqual(triggered["status"], "STOP_TRIGGERED")
        t2 = later + timedelta(seconds=5)
        obs2 = observation(observed_at=t2, bid=1438.0, ask=1439.0, bid_qty=100)
        out2 = sp.evaluate_position_exit(triggered, obs2, now=t2)
        self.assertEqual(out2["status"], "CLOSED")
        self.assertEqual(out2["exit_reason"], "STOP")
        self.assertEqual(out2["avg_exit_price"], 1438.0)

    def test_golden_12_short_stop_fills_at_ask(self):
        intent = entry_intent(side="SELL", planned_entry=1500.0, planned_stop=1550.0, planned_target=1400.0)
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        triggered = sp.evaluate_position_exit(
            pos, observation(observed_at=later, last_trade_price=1560.0), now=later)
        self.assertEqual(triggered["status"], "STOP_TRIGGERED")
        t2 = later + timedelta(seconds=5)
        obs2 = observation(observed_at=t2, bid=1561.0, ask=1562.0, ask_qty=100)
        out2 = sp.evaluate_position_exit(triggered, obs2, now=t2)
        self.assertEqual(out2["status"], "CLOSED")
        self.assertEqual(out2["exit_reason"], "STOP")
        self.assertEqual(out2["avg_exit_price"], 1562.0)


class Golden13GapThroughStopTests(unittest.TestCase):
    def test_golden_13_gap_through_stop_uses_observed_bbo_not_planned_stop(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        triggered = sp.evaluate_position_exit(
            pos, observation(observed_at=later, last_trade_price=1300.0, bid=1299.0, ask=1300.0), now=later)
        self.assertEqual(triggered["status"], "STOP_TRIGGERED")
        t2 = later + timedelta(seconds=5)
        obs2 = observation(observed_at=t2, bid=1250.0, ask=1251.0, bid_qty=100)
        out2 = sp.evaluate_position_exit(triggered, obs2, now=t2)
        self.assertEqual(out2["status"], "CLOSED")
        self.assertEqual(out2["avg_exit_price"], 1250.0)
        self.assertNotEqual(out2["avg_exit_price"], 1450.0)


class Golden14PartialStopExitTests(unittest.TestCase):
    def test_golden_14_insufficient_visible_qty_partial_then_completes(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        triggered = sp.evaluate_position_exit(
            pos, observation(observed_at=later, last_trade_price=1440.0), now=later)
        t2 = later + timedelta(seconds=5)
        partial = sp.evaluate_position_exit(
            triggered, observation(observed_at=t2, bid=1439.0, bid_qty=30), now=t2)
        self.assertEqual(partial["status"], "STOP_EXIT_PARTIAL")
        self.assertEqual(partial["current_qty"], 70)
        self.assertEqual(partial["exit_filled_qty"], 30)
        t3 = t2 + timedelta(seconds=5)
        done = sp.evaluate_position_exit(
            partial, observation(observed_at=t3, bid=1438.0, bid_qty=70), now=t3)
        self.assertEqual(done["status"], "CLOSED")
        self.assertEqual(done["current_qty"], 0)
        self.assertEqual(done["exit_filled_qty"], 100)
        self.assertEqual(done["exit_reason"], "STOP")


class Golden15DuplicateWatermarkTests(unittest.TestCase):
    def test_golden_15_duplicate_observation_does_not_double_fill_partial_exit(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        triggered = sp.evaluate_position_exit(
            pos, observation(observed_at=later, last_trade_price=1440.0), now=later)
        t2 = later + timedelta(seconds=5)
        obs2 = observation(observed_at=t2, bid=1439.0, bid_qty=30)
        partial = sp.evaluate_position_exit(triggered, obs2, now=t2)
        self.assertEqual(partial["exit_filled_qty"], 30)
        replay = sp.evaluate_position_exit(partial, obs2, now=t2)
        self.assertEqual(replay["exit_filled_qty"], 30)
        self.assertEqual(replay["current_qty"], 70)
        self.assertEqual(replay["fill_reason"], "DUPLICATE_POSITION_OBSERVATION")

    def test_golden_15_out_of_order_observation_rejected(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        triggered = sp.evaluate_position_exit(
            pos, observation(observed_at=later, last_trade_price=1440.0), now=later)
        t2 = later + timedelta(seconds=5)
        partial = sp.evaluate_position_exit(
            triggered, observation(observed_at=t2, bid=1439.0, bid_qty=30), now=t2)
        stale_t = later + timedelta(seconds=1)
        replay = sp.evaluate_position_exit(
            partial, observation(observed_at=stale_t, bid=1200.0, bid_qty=70), now=t2)
        self.assertEqual(replay["exit_filled_qty"], 30)
        self.assertEqual(replay["fill_reason"], "OUT_OF_ORDER_POSITION_OBSERVATION")


class Golden16StaleMalformedTests(unittest.TestCase):
    def test_golden_16_stale_observation_cannot_trigger_stop(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        obs = observation(observed_at=later, last_trade_price=1440.0, data_freshness="STALE")
        out = sp.evaluate_position_exit(pos, obs, now=later)
        self.assertEqual(out["status"], "OPEN")

    def test_golden_16_future_observation_cannot_trigger_stop(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        obs = observation(observed_at=later + timedelta(seconds=100), last_trade_price=1440.0)
        out = sp.evaluate_position_exit(pos, obs, now=later)
        self.assertEqual(out["status"], "OPEN")

    def test_golden_16_malformed_dict_observation_does_not_crash_or_fill(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        out = sp.evaluate_position_exit(pos, {"not": "a valid observation"}, now=NOW + timedelta(seconds=5))
        self.assertEqual(out["status"], "OPEN")

    def test_golden_16_none_observation_does_not_crash(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        out = sp.evaluate_position_exit(pos, None, now=NOW + timedelta(seconds=5))
        self.assertEqual(out["status"], "OPEN")


class Golden17StopDisablesTargetAndEntryGrowthTests(unittest.TestCase):
    def test_golden_17_after_stop_trigger_target_disabled_and_entry_growth_blocked(self):
        intent = entry_intent()
        order = filled_order(intent, ask_qty=40)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        triggered = sp.evaluate_position_exit(
            pos, observation(observed_at=later, last_trade_price=1440.0), now=later)
        self.assertEqual(triggered["status"], "STOP_TRIGGERED")

        t2 = later + timedelta(seconds=5)
        out2 = sp.evaluate_position_exit(
            triggered, observation(observed_at=t2, last_trade_price=1700.0, bid=1699.0, ask=1700.0, bid_qty=40),
            now=t2)
        self.assertEqual(out2["status"], "CLOSED")
        self.assertEqual(out2["exit_reason"], "STOP")

        order2 = se.evaluate_shadow_fill(order, observation(observed_at=t2, ask_qty=60), now=t2)
        synced = sp.sync_entry_fill(triggered, order2, now=t2)
        self.assertIn("BLOCKED_POSITION_NOT_OPEN", synced["entry_sync_reasons"])
        self.assertEqual(synced["current_qty"], 40)


class Golden18AmbiguousOrderingTests(unittest.TestCase):
    def test_golden_18_same_timestamp_entry_exit_ambiguity_rejected(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        obs = observation(observed_at=NOW, last_trade_price=1440.0)
        out = sp.evaluate_position_exit(pos, obs, now=NOW)
        self.assertEqual(out["status"], "OPEN")
        self.assertEqual(out["fill_reason"], "AMBIGUOUS_ENTRY_EXIT_ORDERING")


class Golden19ClosedTerminalTests(unittest.TestCase):
    def test_golden_19_closed_is_terminal_and_idempotent(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        closed = sp.evaluate_position_exit(pos, observation(observed_at=later, last_trade_price=1601.0), now=later)
        self.assertEqual(closed["status"], "CLOSED")

        t2 = later + timedelta(seconds=5)
        replay = sp.evaluate_position_exit(
            closed, observation(observed_at=t2, last_trade_price=1440.0), now=t2)
        self.assertEqual(replay["status"], "CLOSED")
        self.assertEqual(replay, closed)

        synced = sp.sync_entry_fill(closed, order, now=t2)
        self.assertEqual(synced, closed)


class Golden20SideSymmetryTests(unittest.TestCase):
    def test_golden_20_sell_target_trade_through_closes(self):
        intent = entry_intent(side="SELL", planned_entry=1500.0, planned_stop=1550.0, planned_target=1400.0)
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        later = NOW + timedelta(seconds=5)
        obs = observation(observed_at=later, last_trade_price=1399.0)
        out = sp.evaluate_position_exit(pos, obs, now=later)
        self.assertEqual(out["status"], "CLOSED")
        self.assertEqual(out["exit_reason"], "TARGET")
        self.assertEqual(out["avg_exit_price"], 1400.0)


class Golden21DeterminismTests(unittest.TestCase):
    def test_golden_21_deterministic_position_id_and_state(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos1 = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        pos2 = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        self.assertEqual(pos1["position_id"], pos2["position_id"])
        self.assertEqual(pos1, pos2)
        expected_id = sp.compute_position_id(order["shadow_order_id"])
        self.assertEqual(pos1["position_id"], expected_id)


class Golden22RealSubmitAllowedTests(unittest.TestCase):
    def test_golden_22_real_submit_allowed_always_false(self):
        intent = entry_intent()
        order = filled_order(intent)
        pos = sp.create_shadow_position(intent, order, now=NOW, known_positions=[])
        self.assertIs(pos["real_submit_allowed"], False)

        later = NOW + timedelta(seconds=5)
        exited = sp.evaluate_position_exit(pos, observation(observed_at=later, last_trade_price=1440.0), now=later)
        self.assertIs(exited["real_submit_allowed"], False)

        synced = sp.sync_entry_fill(pos, order, now=later)
        self.assertIs(synced["real_submit_allowed"], False)

        rejected = sp.create_shadow_position({**intent, "intent_hash": "0" * 64}, order, now=NOW,
                                              known_positions=[])
        self.assertIs(rejected["real_submit_allowed"], False)


class Golden23NoBrokerReferenceTests(unittest.TestCase):
    """Golden #23: RssOrder/broker/COM/network/Excel発注/file I/Oへの
    side effectがゼロであることをAST上で検査する
    （test_shadow_execution.pyのNoBrokerReferenceTestsと同一方針）。"""

    def test_shadow_position_has_no_broker_rss_or_network_references(self):
        self._assert_clean(ROOT / "scripts/shadow_position.py")

    def _assert_clean(self, path):
        import ast
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden_names = {"RssOrder", "win32com", "pywin32", "xlwings", "openpyxl"}
        forbidden_modules = {"win32com", "requests", "urllib", "socket", "http", "xlwings", "openpyxl"}
        forbidden_calls = {"open", "write_text", "write", "read_text", "read"}
        found = set()
        imported = set()
        io_calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden_names:
                found.add(node.id)
            elif isinstance(node, ast.Attribute) and node.attr in forbidden_names:
                found.add(node.attr)
            elif isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else None)
                if name in forbidden_calls:
                    io_calls.add(name)
        self.assertEqual(found, set())
        self.assertEqual(imported & forbidden_modules, set())
        self.assertEqual(io_calls, set(), "shadow position core must perform no file I/O at all")


if __name__ == "__main__":
    unittest.main()
