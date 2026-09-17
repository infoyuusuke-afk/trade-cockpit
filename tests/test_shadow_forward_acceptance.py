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
sfa = _load('sfa', 'scripts/shadow_forward_acceptance.py')

NOW = datetime(2026, 9, 17, 9, 0, 0, tzinfo=JST)
SUBMITTED_AT = NOW - timedelta(seconds=10)


def build_intent(**overrides):
    kwargs = dict(
        symbol="285A.T", side="BUY", quantity=100, order_type="MARKET",
        limit_price=None, planned_entry=1500.0, planned_stop=1450.0, planned_target=1600.0,
        strategy_id="day_ifo_long", strategy_version="1.0",
        decision_snapshot_id="snap-1", signal_known_at="2026-09-17T08:55:00+09:00",
        risk_policy_version="risk-gate-0.1.0", execution_policy_version="exec-v0.1",
        shadow_fill_model_version="shadow-fill-model-0.1", merge_hash="m" * 64,
    )
    kwargs.update(overrides)
    return ec.build_intent(**kwargs)


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


def build_record(intent, *, steps, recorded_final_shadow_order_status,
                  recorded_final_position_status=None, known_ids=None,
                  source="SHADOW_FORWARD", session_date="2026-09-17", source_path=None,
                  fill_confidence=None, submitted_at=SUBMITTED_AT, submit_now=NOW,
                  risk_decision_override=None, ticket_override=None):
    rd = risk_decision_override if risk_decision_override is not None else risk_decision()
    tkt = ticket_override if ticket_override is not None else ticket(intent)
    shadow_order_id = se.compute_shadow_order_id(intent["intent_hash"], intent["shadow_fill_model_version"])
    return {
        "source": source,
        "session_date": session_date,
        "intent_hash": intent["intent_hash"],
        "shadow_order_id": shadow_order_id,
        "strategy_id": intent["strategy_id"],
        "strategy_version": intent["strategy_version"],
        "shadow_fill_model_version": intent["shadow_fill_model_version"],
        "execution_policy_version": intent["execution_policy_version"],
        "risk_policy_version": intent["risk_policy_version"],
        "ticket_fingerprint": tkt["ticket_fingerprint"],
        "merge_hash": intent["merge_hash"],
        "intent": intent,
        "risk_decision": rd,
        "ticket": tkt,
        "submitted_at": submitted_at,
        "submit_now": submit_now,
        "known_shadow_order_ids_at_submission": known_ids or [],
        "steps": steps,
        "recorded_final_shadow_order_status": recorded_final_shadow_order_status,
        "recorded_final_position_status": recorded_final_position_status,
        "fill_confidence": fill_confidence,
        "source_path": source_path,
    }


def healthy_filled_record_from_intent(intent, **overrides):
    """MARKET BUY 100が単発observationで即FILLEDし、Position OPENになる
    最小限の健全なforward record。"""
    kwargs = dict(
        steps=[{"type": "ORDER_FILL", "observation": observation(), "now": NOW}],
        recorded_final_shadow_order_status="FILLED",
        recorded_final_position_status="OPEN",
        fill_confidence="PROBABLE",
    )
    kwargs.update(overrides)
    return build_record(intent, **kwargs)


def healthy_filled_record(*, decision_snapshot_id, session_date="2026-09-17"):
    intent = build_intent(decision_snapshot_id=decision_snapshot_id)
    return healthy_filled_record_from_intent(intent, session_date=session_date)


def make_n_healthy_records(n, start=1):
    return [healthy_filled_record(decision_snapshot_id=f"snap-{start + i}") for i in range(n)]


class Golden1InsufficientSampleTests(unittest.TestCase):
    def test_golden_1_fewer_than_50_gives_insufficient_sample(self):
        records = make_n_healthy_records(49)
        report = sfa.evaluate_shadow_forward_acceptance(records, now=NOW)
        self.assertEqual(report["status"], "INSUFFICIENT_SAMPLE")
        self.assertEqual(report["eligible_unique_intents"], 49)

    def test_golden_1_zero_records_gives_insufficient_sample(self):
        report = sfa.evaluate_shadow_forward_acceptance([], now=NOW)
        self.assertEqual(report["status"], "INSUFFICIENT_SAMPLE")
        self.assertEqual(report["eligible_unique_intents"], 0)


class Golden2ReviewEligibleTests(unittest.TestCase):
    def test_golden_2_exactly_50_healthy_gives_review_eligible(self):
        records = make_n_healthy_records(50)
        report = sfa.evaluate_shadow_forward_acceptance(records, now=NOW)
        self.assertEqual(report["status"], "SHADOW_FORWARD_REVIEW_ELIGIBLE")
        self.assertEqual(report["eligible_unique_intents"], 50)
        self.assertEqual(report["effective_duplicate_accept_n"], 0)
        self.assertEqual(report["stale_or_future_state_advance_n"], 0)
        self.assertEqual(report["kill_or_permission_bypass_n"], 0)
        self.assertEqual(report["deterministic_replay_mismatch_n"], 0)
        self.assertEqual(report["private_path_leak_n"], 0)
        self.assertIs(report["real_submit_allowed"], False)

    def test_golden_2_50_with_one_violation_is_not_eligible(self):
        records = make_n_healthy_records(50)
        records[0] = {**records[0], "recorded_final_shadow_order_status": "PARTIAL_FILLED"}
        report = sfa.evaluate_shadow_forward_acceptance(records, now=NOW)
        self.assertEqual(report["status"], "FAIL_INTEGRITY")
        self.assertGreaterEqual(report["deterministic_replay_mismatch_n"], 1)


class Golden3RepeatedIdTests(unittest.TestCase):
    def test_golden_3_repeated_shadow_order_id_does_not_increase_eligible_count(self):
        intent = build_intent(decision_snapshot_id="snap-dup")
        first = healthy_filled_record_from_intent(intent)
        second = dict(first)
        report = sfa.evaluate_shadow_forward_acceptance([first, second], now=NOW)
        self.assertEqual(report["eligible_unique_intents"], 1)
        self.assertEqual(report["effective_duplicate_accept_n"], 1)

    def test_golden_5_effective_duplicate_acceptance_fails_integrity(self):
        intent = build_intent(decision_snapshot_id="snap-dup2")
        first = healthy_filled_record_from_intent(intent)
        second = dict(first)
        report = sfa.evaluate_shadow_forward_acceptance([first, second], now=NOW)
        self.assertEqual(report["status"], "FAIL_INTEGRITY")


class Golden4DuplicateGuardHitTests(unittest.TestCase):
    def test_golden_4_duplicate_guard_hit_counted_diagnostically_not_as_exposure(self):
        intent = build_intent(decision_snapshot_id="snap-guard")
        first = healthy_filled_record_from_intent(intent)
        shadow_order_id = first["shadow_order_id"]
        second = healthy_filled_record_from_intent(
            intent, known_ids=[shadow_order_id],
            recorded_final_shadow_order_status="DUPLICATE_IGNORED",
            recorded_final_position_status=None,
        )
        report = sfa.evaluate_shadow_forward_acceptance([first, second], now=NOW)
        self.assertEqual(report["eligible_unique_intents"], 1)
        self.assertEqual(report["duplicate_guard_hit_n"], 1)
        self.assertEqual(report["effective_duplicate_accept_n"], 0)
        self.assertEqual(report["deterministic_replay_mismatch_n"], 0)


class Golden6And7StaleObservationTests(unittest.TestCase):
    def test_golden_6_stale_observation_ignored_increments_diagnostics_only(self):
        intent = build_intent(decision_snapshot_id="snap-stale-ok")
        later = NOW + timedelta(seconds=1)
        steps = [
            {"type": "ORDER_FILL", "observation": observation(data_freshness="STALE"), "now": NOW},
            {"type": "ORDER_FILL", "observation": observation(observed_at=later), "now": later},
        ]
        rec = build_record(intent, steps=steps, recorded_final_shadow_order_status="FILLED",
                            recorded_final_position_status="OPEN")
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=later)
        self.assertGreaterEqual(report["invalid_input_observation_n"], 1)
        self.assertGreaterEqual(report["stale_input_n"], 1)
        self.assertEqual(report["stale_or_future_state_advance_n"], 0)
        self.assertEqual(report["deterministic_replay_mismatch_n"], 0)
        self.assertEqual(report["eligible_unique_intents"], 1)

    def test_golden_7_stale_observation_falsely_recorded_as_filled_fails_integrity(self):
        intent = build_intent(decision_snapshot_id="snap-stale-bad")
        steps = [{"type": "ORDER_FILL", "observation": observation(data_freshness="STALE"), "now": NOW}]
        rec = build_record(intent, steps=steps, recorded_final_shadow_order_status="FILLED",
                            recorded_final_position_status="OPEN")
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=NOW)
        self.assertEqual(report["status"], "FAIL_INTEGRITY")
        self.assertGreaterEqual(report["deterministic_replay_mismatch_n"], 1)
        self.assertEqual(report["eligible_unique_intents"], 0)

    def test_future_observation_falsely_recorded_as_filled_fails_integrity(self):
        intent = build_intent(decision_snapshot_id="snap-future-bad")
        far_future = NOW + timedelta(days=1)
        steps = [{"type": "ORDER_FILL", "observation": observation(observed_at=far_future), "now": NOW}]
        rec = build_record(intent, steps=steps, recorded_final_shadow_order_status="FILLED",
                            recorded_final_position_status="OPEN")
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=NOW)
        self.assertEqual(report["status"], "FAIL_INTEGRITY")
        self.assertGreaterEqual(report["future_input_n"], 1)


class Golden8PermissionBypassTests(unittest.TestCase):
    def test_golden_8_permission_bypass_fails_integrity(self):
        intent = build_intent(decision_snapshot_id="snap-bypass")
        bad_risk_decision = risk_decision(decision="BLOCK")
        steps = [{"type": "ORDER_FILL", "observation": observation(), "now": NOW}]
        rec = build_record(intent, steps=steps, recorded_final_shadow_order_status="FILLED",
                            recorded_final_position_status="OPEN", risk_decision_override=bad_risk_decision)
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=NOW)
        self.assertEqual(report["status"], "FAIL_INTEGRITY")
        self.assertGreaterEqual(report["kill_or_permission_bypass_n"], 1)

    def test_golden_8_not_ready_ticket_bypass_fails_integrity(self):
        intent = build_intent(decision_snapshot_id="snap-bypass2")
        bad_ticket = ticket(intent, permission_status="PERMISSION_BLOCKED")
        steps = [{"type": "ORDER_FILL", "observation": observation(), "now": NOW}]
        rec = build_record(intent, steps=steps, recorded_final_shadow_order_status="FILLED",
                            recorded_final_position_status="OPEN", ticket_override=bad_ticket)
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=NOW)
        self.assertEqual(report["status"], "FAIL_INTEGRITY")
        self.assertGreaterEqual(report["kill_or_permission_bypass_n"], 1)


class Golden9DeterministicReplayMismatchTests(unittest.TestCase):
    def test_golden_9_tampered_intent_hash_causes_replay_mismatch(self):
        intent = build_intent(decision_snapshot_id="snap-tamper")
        tampered_intent = {**intent, "intent_hash": "0" * 64}
        steps = [{"type": "ORDER_FILL", "observation": observation(), "now": NOW}]
        rec = build_record(tampered_intent, steps=steps, recorded_final_shadow_order_status="FILLED",
                            recorded_final_position_status="OPEN")
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=NOW)
        self.assertEqual(report["status"], "FAIL_INTEGRITY")
        self.assertGreaterEqual(report["deterministic_replay_mismatch_n"], 1)


class Golden10ReplayNeverInflatesTests(unittest.TestCase):
    def test_golden_10_replay_never_inflates_n(self):
        records = make_n_healthy_records(50)
        report1 = sfa.evaluate_shadow_forward_acceptance(records, now=NOW)
        report2 = sfa.evaluate_shadow_forward_acceptance(records, now=NOW)
        self.assertEqual(report1["eligible_unique_intents"], 50)
        self.assertEqual(report1["eligible_unique_intents"], report2["eligible_unique_intents"])
        self.assertEqual(report1, report2)


class Golden11And12ProvenanceTests(unittest.TestCase):
    def test_golden_11_non_forward_source_never_counts(self):
        intent = build_intent(decision_snapshot_id="snap-nonforward")
        rec = healthy_filled_record_from_intent(intent, source="UNIT_TEST")
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=NOW)
        self.assertEqual(report["eligible_unique_intents"], 0)
        self.assertEqual(report["ambiguous_provenance_n"], 1)

    def test_golden_11_backtest_source_never_counts(self):
        intent = build_intent(decision_snapshot_id="snap-backtest")
        rec = healthy_filled_record_from_intent(intent, source="BACKTEST")
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=NOW)
        self.assertEqual(report["eligible_unique_intents"], 0)
        self.assertEqual(report["ambiguous_provenance_n"], 1)

    def test_golden_12_missing_ticket_fingerprint_not_eligible(self):
        intent = build_intent(decision_snapshot_id="snap-missing")
        rec = healthy_filled_record_from_intent(intent)
        del rec["ticket_fingerprint"]
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=NOW)
        self.assertEqual(report["eligible_unique_intents"], 0)
        self.assertEqual(report["ambiguous_provenance_n"], 1)

    def test_golden_12_empty_steps_not_eligible(self):
        intent = build_intent(decision_snapshot_id="snap-nosteps")
        rec = healthy_filled_record_from_intent(intent, steps=[])
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=NOW)
        self.assertEqual(report["eligible_unique_intents"], 0)
        self.assertEqual(report["ambiguous_provenance_n"], 1)

    def test_golden_12_mismatched_shadow_order_id_not_eligible(self):
        intent = build_intent(decision_snapshot_id="snap-idmismatch")
        rec = healthy_filled_record_from_intent(intent)
        rec = {**rec, "shadow_order_id": "z" * 64}
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=NOW)
        self.assertEqual(report["eligible_unique_intents"], 0)
        self.assertEqual(report["ambiguous_provenance_n"], 1)


class Golden13PrivatePathTests(unittest.TestCase):
    def test_golden_13_helper_rejects_outside_approved_root(self):
        self.assertFalse(sfa.is_approved_private_path("data/public/shadow_forward/x.json"))
        self.assertFalse(sfa.is_approved_private_path("/etc/passwd"))
        self.assertFalse(sfa.is_approved_private_path("../secret.json"))
        self.assertFalse(sfa.is_approved_private_path(""))
        self.assertFalse(sfa.is_approved_private_path(None))

    def test_golden_13_helper_accepts_approved_roots(self):
        self.assertTrue(sfa.is_approved_private_path("data/private/shadow_forward/2026-09-17.jsonl"))
        self.assertTrue(sfa.is_approved_private_path("ms2_live/records/2026-09-17/foo.csv"))

    def test_golden_13_record_with_leaked_source_path_rejected(self):
        intent = build_intent(decision_snapshot_id="snap-leak")
        rec = healthy_filled_record_from_intent(intent, source_path="data/public/leak.json")
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=NOW)
        self.assertEqual(report["eligible_unique_intents"], 0)
        self.assertEqual(report["private_path_leak_n"], 1)
        self.assertEqual(report["status"], "FAIL_INTEGRITY")

    def test_record_with_approved_source_path_is_fine(self):
        intent = build_intent(decision_snapshot_id="snap-safe-path")
        rec = healthy_filled_record_from_intent(
            intent, source_path="data/private/shadow_forward/2026-09-17.jsonl")
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=NOW)
        self.assertEqual(report["private_path_leak_n"], 0)
        self.assertEqual(report["eligible_unique_intents"], 1)


class PositionExitStepTests(unittest.TestCase):
    """steps内のPOSITION_EXITも正しくreplayされ、正常なSTOP_TRIGGERED等の
    位相まで一致すること（ORDER_FILLのみのrecordに限定されないことの
    追加確認）。"""

    def test_stop_triggered_lifecycle_replays_consistently(self):
        intent = build_intent(decision_snapshot_id="snap-stop-lifecycle")
        later = NOW + timedelta(seconds=5)
        steps = [
            {"type": "ORDER_FILL", "observation": observation(), "now": NOW},
            {"type": "POSITION_EXIT", "observation": observation(observed_at=later, last_trade_price=1440.0),
             "now": later},
        ]
        rec = build_record(intent, steps=steps, recorded_final_shadow_order_status="FILLED",
                            recorded_final_position_status="STOP_TRIGGERED")
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=later)
        self.assertEqual(report["eligible_unique_intents"], 1)
        self.assertEqual(report["deterministic_replay_mismatch_n"], 0)

    def test_position_exit_before_any_fill_is_flagged(self):
        intent = build_intent(decision_snapshot_id="snap-exit-before-fill")
        steps = [
            {"type": "POSITION_EXIT", "observation": observation(last_trade_price=1440.0), "now": NOW},
        ]
        rec = build_record(intent, steps=steps, recorded_final_shadow_order_status="NEW",
                            recorded_final_position_status=None)
        report = sfa.evaluate_shadow_forward_acceptance([rec], now=NOW)
        self.assertGreaterEqual(report["stale_or_future_state_advance_n"], 1)
        self.assertEqual(report["status"], "FAIL_INTEGRITY")


class DiagnosticsDistributionTests(unittest.TestCase):
    def test_diagnostics_distributions_populated(self):
        records = make_n_healthy_records(50)
        report = sfa.evaluate_shadow_forward_acceptance(records, now=NOW)
        self.assertEqual(report["unique_session_days"], 1)
        self.assertIn("day_ifo_long|1.0", report["strategy_distribution"])
        self.assertEqual(report["strategy_distribution"]["day_ifo_long|1.0"], 50)
        self.assertIn("285A.T", report["symbol_distribution"])
        self.assertEqual(report["symbol_distribution"]["285A.T"], 50)
        self.assertIn("PROBABLE", report["fill_confidence_distribution"])


class Golden16NoBrokerReferenceTests(unittest.TestCase):
    """Golden #16: RssOrder/broker/COM/network/Excel発注/file I/Oへの
    side effectがゼロであることをAST上で検査する（test_shadow_position.py
    のGolden23NoBrokerReferenceTestsと同一方針）。"""

    def test_shadow_forward_acceptance_has_no_broker_rss_or_network_references(self):
        self._assert_clean(ROOT / "scripts/shadow_forward_acceptance.py")

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
        self.assertEqual(io_calls, set(), "shadow forward acceptance core must perform no file I/O at all")

    def test_status_vocabulary_never_includes_real_promotion_states(self):
        forbidden = {"REAL_ALLOWED", "REAL_READY", "AUTHORIZED_FOR_REAL"}
        self.assertEqual(set(sfa.STATUSES) & forbidden, set())

    def test_real_submit_allowed_always_false_in_reports(self):
        records = make_n_healthy_records(5)
        report = sfa.evaluate_shadow_forward_acceptance(records, now=NOW)
        self.assertIs(report["real_submit_allowed"], False)
        empty_report = sfa.evaluate_shadow_forward_acceptance([], now=NOW)
        self.assertIs(empty_report["real_submit_allowed"], False)


if __name__ == "__main__":
    unittest.main()
