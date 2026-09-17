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

NOW = datetime(2026, 9, 17, 9, 0, 0, tzinfo=JST)


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


class ShadowOrderIdTests(unittest.TestCase):
    def test_golden_1_same_intent_and_model_gives_same_id(self):
        a = se.compute_shadow_order_id("h" * 64, "shadow-fill-model-0.1")
        b = se.compute_shadow_order_id("h" * 64, "shadow-fill-model-0.1")
        self.assertEqual(a, b)

    def test_different_model_version_gives_different_id(self):
        a = se.compute_shadow_order_id("h" * 64, "shadow-fill-model-0.1")
        b = se.compute_shadow_order_id("h" * 64, "shadow-fill-model-0.2")
        self.assertNotEqual(a, b)

    def test_different_intent_hash_gives_different_id(self):
        a = se.compute_shadow_order_id("h" * 64, "shadow-fill-model-0.1")
        b = se.compute_shadow_order_id("z" * 64, "shadow-fill-model-0.1")
        self.assertNotEqual(a, b)


class SubmitShadowOrderHappyPathTests(unittest.TestCase):
    def test_valid_lineage_gives_new_status(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent)
        out = se.submit_shadow_order(intent, decision, tkt, known_orders=[])
        self.assertEqual(out["status"], "NEW")
        self.assertEqual(out["real_submit_allowed"], False)
        expected_id = se.compute_shadow_order_id(intent["intent_hash"], intent["shadow_fill_model_version"])
        self.assertEqual(out["shadow_order_id"], expected_id)
        self.assertEqual(out["merge_hash"], "m" * 64)
        self.assertEqual(out["requested_qty"], 100)
        self.assertEqual(out["remaining_qty"], 100)


class DuplicateGuardTests(unittest.TestCase):
    def test_golden_2_duplicate_intent_gives_duplicate_ignored_no_double_order(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent)
        first = se.submit_shadow_order(intent, decision, tkt, known_orders=[])
        second = se.submit_shadow_order(intent, decision, tkt, known_orders=[first])
        self.assertEqual(second["status"], "DUPLICATE_IGNORED")
        self.assertEqual(second["shadow_order_id"], first["shadow_order_id"])

    def test_unrelated_known_order_does_not_block(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent)
        unrelated = {"shadow_order_id": "z" * 64}
        out = se.submit_shadow_order(intent, decision, tkt, known_orders=[unrelated])
        self.assertEqual(out["status"], "NEW")


class LineageRejectionTests(unittest.TestCase):
    """Golden #3-#7: lineageが不正ならREJECTED。"""

    def test_golden_3_mismatched_intent_hash_rejected(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent, intent_hash="0" * 64)
        out = se.submit_shadow_order(intent, decision, tkt, known_orders=[])
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_INTENT_HASH_MISMATCH", out["reject_reasons"])
        self.assertIsNone(out["shadow_order_id"])

    def test_golden_4_risk_decision_merge_hash_mismatch_rejected(self):
        intent = build_intent()
        decision = risk_decision(merge_hash="z" * 64)
        tkt = ticket(intent)
        out = se.submit_shadow_order(intent, decision, tkt, known_orders=[])
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_MERGE_HASH_MISMATCH", out["reject_reasons"])

    def test_golden_4_ticket_merge_hash_mismatch_rejected(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent, merge_hash="z" * 64)
        out = se.submit_shadow_order(intent, decision, tkt, known_orders=[])
        self.assertIn("REJECTED_MERGE_HASH_MISMATCH", out["reject_reasons"])

    def test_golden_5_risk_decision_not_pass_rejected(self):
        intent = build_intent()
        decision = risk_decision(decision="BLOCK")
        tkt = ticket(intent)
        out = se.submit_shadow_order(intent, decision, tkt, known_orders=[])
        self.assertIn("REJECTED_RISK_DECISION_NOT_PASS", out["reject_reasons"])

    def test_golden_6_permission_status_not_ready_rejected(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent, permission_status="BLOCKED")
        out = se.submit_shadow_order(intent, decision, tkt, known_orders=[])
        self.assertIn("REJECTED_TICKET_NOT_READY", out["reject_reasons"])

    def test_golden_7_real_submit_allowed_true_rejected(self):
        intent = {**build_intent(), "real_submit_allowed": True}
        decision = risk_decision()
        tkt = ticket(intent)
        out = se.submit_shadow_order(intent, decision, tkt, known_orders=[])
        self.assertIn("REJECTED_REAL_SUBMIT_ALLOWED_NOT_FALSE", out["reject_reasons"])

    def test_quantity_mismatch_rejected(self):
        intent = build_intent(quantity=100)
        decision = risk_decision(allowed_qty=200)
        tkt = ticket(intent)
        out = se.submit_shadow_order(intent, decision, tkt, known_orders=[])
        self.assertIn("REJECTED_QUANTITY_MISMATCH", out["reject_reasons"])

    def test_risk_policy_version_mismatch_rejected(self):
        intent = build_intent(risk_policy_version="risk-gate-0.1.0")
        decision = risk_decision(policy_version="risk-gate-9.9.9")
        tkt = ticket(intent)
        out = se.submit_shadow_order(intent, decision, tkt, known_orders=[])
        self.assertIn("REJECTED_RISK_POLICY_VERSION_MISMATCH", out["reject_reasons"])

    def test_intent_hash_tampered_rejected(self):
        """intent_hashフィールド自体はticketと一致していても、中身
        （quantity）だけ書き換えられ再計算hashと食い違う場合を検出する。"""
        intent = {**build_intent(), "quantity": 999}
        decision = risk_decision(allowed_qty=999)
        tkt = ticket(intent)
        out = se.submit_shadow_order(intent, decision, tkt, known_orders=[])
        self.assertIn("REJECTED_INTENT_HASH_TAMPERED", out["reject_reasons"])

    def test_non_list_known_orders_rejected(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent)
        out = se.submit_shadow_order(intent, decision, tkt, known_orders=None)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_KNOWN_ORDERS_INVALID", out["reject_reasons"])


class EvaluateShadowFillTests(unittest.TestCase):
    def _new_order(self, order_type="MARKET", **intent_overrides):
        overrides = dict(order_type=order_type)
        if order_type == "MARKET":
            overrides["limit_price"] = None
        overrides.update(intent_overrides)
        intent = build_intent(**overrides)
        decision = risk_decision()
        tkt = ticket(intent)
        return se.submit_shadow_order(intent, decision, tkt, known_orders=[])

    def test_market_fill_transitions_to_filled(self):
        order = self._new_order("MARKET")
        out = se.evaluate_shadow_fill(order, observation(), now=NOW, submitted_at=NOW - timedelta(seconds=5))
        self.assertEqual(out["status"], "FILLED")
        self.assertEqual(out["filled_qty"], 100)
        self.assertEqual(out["remaining_qty"], 0)
        self.assertEqual(out["fill_at"], NOW)
        self.assertEqual(out["first_observation_at"], NOW)
        self.assertEqual(out["real_submit_allowed"], False)

    def test_market_partial_fill_status(self):
        order = self._new_order("MARKET")
        out = se.evaluate_shadow_fill(order, observation(ask_qty=40), now=NOW,
                                       submitted_at=NOW - timedelta(seconds=5))
        self.assertEqual(out["status"], "PARTIAL_FILLED")
        self.assertEqual(out["filled_qty"], 40)
        self.assertEqual(out["remaining_qty"], 60)
        self.assertIn("PARTIAL_FILL", out["ambiguity_flags"])

    def test_limit_touch_only_stays_working_with_ambiguity_flag(self):
        order = self._new_order("LIMIT", limit_price=1500.0)
        submitted_at = NOW - timedelta(seconds=5)
        out = se.evaluate_shadow_fill(order, observation(last_trade_price=1500.0), now=NOW, submitted_at=submitted_at)
        self.assertEqual(out["status"], "WORKING")
        self.assertIn("TOUCH_ONLY", out["ambiguity_flags"])
        self.assertEqual(out["filled_qty"], 0)

    def test_limit_trade_through_fills(self):
        order = self._new_order("LIMIT", limit_price=1500.0)
        submitted_at = NOW - timedelta(seconds=5)
        out = se.evaluate_shadow_fill(order, observation(last_trade_price=1490.0), now=NOW, submitted_at=submitted_at)
        self.assertEqual(out["status"], "FILLED")
        self.assertEqual(out["filled_qty"], 100)

    def test_unobservable_data_gives_unobservable_status(self):
        order = self._new_order("MARKET")
        out = se.evaluate_shadow_fill(order, observation(data_freshness="STALE"), now=NOW,
                                       submitted_at=NOW - timedelta(seconds=5))
        self.assertEqual(out["status"], "UNOBSERVABLE")
        self.assertEqual(out["filled_qty"], 0)

    def test_golden_17_terminal_filled_state_not_reevaluated(self):
        """FILLED状態のshadow_orderへ、全く異なるobservationを渡しても
        一切変化しない（自動retryしない）。"""
        order = self._new_order("MARKET")
        filled = se.evaluate_shadow_fill(order, observation(), now=NOW, submitted_at=NOW - timedelta(seconds=5))
        self.assertEqual(filled["status"], "FILLED")
        later = NOW + timedelta(seconds=30)
        reevaluated = se.evaluate_shadow_fill(
            filled, observation(observed_at=later, ask=9999.0), now=later, submitted_at=NOW - timedelta(seconds=5))
        self.assertEqual(reevaluated, filled)

    def test_golden_17_rejected_state_not_reevaluated(self):
        intent = build_intent()
        decision = risk_decision(decision="BLOCK")
        tkt = ticket(intent)
        rejected = se.submit_shadow_order(intent, decision, tkt, known_orders=[])
        self.assertEqual(rejected["status"], "REJECTED")
        out = se.evaluate_shadow_fill(rejected, observation(), now=NOW, submitted_at=NOW)
        self.assertEqual(out, rejected)

    def test_golden_17_duplicate_ignored_state_not_reevaluated(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent)
        first = se.submit_shadow_order(intent, decision, tkt, known_orders=[])
        duplicate = se.submit_shadow_order(intent, decision, tkt, known_orders=[first])
        self.assertEqual(duplicate["status"], "DUPLICATE_IGNORED")
        out = se.evaluate_shadow_fill(duplicate, observation(), now=NOW, submitted_at=NOW)
        self.assertEqual(out, duplicate)


class RealSubmitAllowedTests(unittest.TestCase):
    """Golden #19: real_submit_allowedは常にfalse。"""

    def test_new_order_real_submit_allowed_false(self):
        intent = build_intent()
        out = se.submit_shadow_order(intent, risk_decision(), ticket(intent), known_orders=[])
        self.assertIs(out["real_submit_allowed"], False)

    def test_rejected_real_submit_allowed_false(self):
        intent = build_intent()
        out = se.submit_shadow_order(intent, risk_decision(decision="BLOCK"), ticket(intent), known_orders=[])
        self.assertIs(out["real_submit_allowed"], False)

    def test_evaluated_fill_real_submit_allowed_false(self):
        intent = build_intent(order_type="MARKET", limit_price=None)
        order = se.submit_shadow_order(intent, risk_decision(), ticket(intent), known_orders=[])
        out = se.evaluate_shadow_fill(order, observation(), now=NOW, submitted_at=NOW - timedelta(seconds=5))
        self.assertIs(out["real_submit_allowed"], False)


class NoBrokerReferenceTests(unittest.TestCase):
    """Golden #18: RssOrder/broker/COM/network/Excel発注のside effectがゼロ。
    Golden #20: data/private/trade_ledger.jsonl（Real ledger）へ一切書かない。
    """

    def test_shadow_execution_has_no_broker_rss_or_network_references(self):
        self._assert_clean(ROOT / "scripts/shadow_execution.py")

    def test_shadow_fill_model_has_no_broker_rss_or_network_references(self):
        self._assert_clean(ROOT / "scripts/shadow_fill_model.py")

    def _assert_clean(self, path):
        """AST上の実行コードノードだけを検査する（docstringがtrade_ledger等の
        境界説明を含むこと自体は許容する——単純な文字列includeだと、その
        安全性の説明そのものが引っかかってしまうため）。"""
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
        self.assertEqual(io_calls, set(), "shadow core must perform no file I/O at all")


if __name__ == "__main__":
    unittest.main()
