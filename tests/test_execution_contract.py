import importlib.util
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[1] / 'scripts/execution_contract.py'
spec = importlib.util.spec_from_file_location('ec', SCRIPT_PATH)
ec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ec)


def base_kwargs(**overrides):
    kwargs = dict(
        symbol="285A.T",
        side="BUY",
        quantity=100,
        order_type="LIMIT",
        limit_price=1500.0,
        planned_entry=1500.0,
        planned_stop=1450.0,
        planned_target=1600.0,
        strategy_id="day_ifo_long",
        strategy_version="1.0",
        decision_snapshot_id="20260917T085500-abcd1234",
        signal_known_at="2026-09-17T08:55:00+09:00",
        risk_policy_version="risk-v0.1",
        execution_policy_version="exec-v0.1",
        shadow_fill_model_version="shadow-v0.1",
    )
    kwargs.update(overrides)
    return kwargs


class NoBrokerImportTests(unittest.TestCase):
    """Golden #12: broker/RSS側への副作用がゼロであることをソースレベルで保証する。

    ASTで実行コード上の参照だけを検査する（docstringの説明文で『RssOrderは実装
    しない』と書くこと自体は許容したい——単純な文字列includeだと、その安全性の
    説明そのものが引っかかってしまうため、Name/Attribute/Import/ImportFromの
    ノードだけを対象にする）。
    """

    def test_source_does_not_call_or_import_broker_apis(self):
        import ast
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        forbidden_names = {"RssOrder", "win32com", "pywin32", "xlwings", "openpyxl"}
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden_names:
                found.add(node.id)
            elif isinstance(node, ast.Attribute) and node.attr in forbidden_names:
                found.add(node.attr)
            elif isinstance(node, ast.Import):
                found |= {alias.name for alias in node.names if alias.name in forbidden_names}
            elif isinstance(node, ast.ImportFrom) and node.module in forbidden_names:
                found.add(node.module)
        self.assertEqual(found, set())

    def test_module_has_no_network_or_com_imports(self):
        import ast
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        forbidden_modules = {"win32com", "requests", "urllib", "socket", "http", "xlwings", "openpyxl"}
        self.assertEqual(imported & forbidden_modules, set())


class BuildIntentValidationTests(unittest.TestCase):
    def test_valid_intent_has_created_status_and_real_submit_false(self):
        intent = ec.build_intent(**base_kwargs())
        self.assertEqual(intent["status"], "CREATED")
        self.assertEqual(intent["real_submit_allowed"], False)
        self.assertEqual(intent["block_reasons"], [])

    def test_invalid_side_is_rejected(self):
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(side="LONG"))
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(side="WAIT"))

    def test_zero_or_negative_quantity_is_rejected(self):
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(quantity=0))
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(quantity=-100))

    def test_nan_and_inf_quantity_rejected(self):
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(quantity=float("nan")))
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(quantity=float("inf")))

    def test_missing_required_field_is_rejected(self):
        kwargs = base_kwargs()
        del kwargs["strategy_id"]
        with self.assertRaises(TypeError):
            ec.build_intent(**kwargs)

    def test_empty_required_string_is_rejected(self):
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(strategy_id=""))
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(symbol=""))

    def test_limit_order_missing_limit_price_rejected(self):
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(order_type="LIMIT", limit_price=None))

    def test_market_order_allows_null_limit_price(self):
        intent = ec.build_intent(**base_kwargs(order_type="MARKET", limit_price=None))
        self.assertIsNone(intent["limit_price"])
        self.assertEqual(intent["status"], "CREATED")

    def test_negative_or_nan_price_rejected(self):
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(limit_price=-100.0))
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(planned_stop=float("nan")))
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(planned_entry=float("inf")))

    def test_invalid_signal_known_at_rejected(self):
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(signal_known_at="not-a-timestamp"))
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(signal_known_at=""))

    def test_real_submit_allowed_is_not_an_accepted_argument(self):
        """Golden #9: real_submit_allowedを渡そうとしても受け付けない。"""
        with self.assertRaises(TypeError):
            ec.build_intent(**base_kwargs(real_submit_allowed=True))

    def test_invalid_order_type_rejected(self):
        with self.assertRaises(ValueError):
            ec.build_intent(**base_kwargs(order_type="STOP"))


class IntentHashDeterminismTests(unittest.TestCase):
    def test_same_input_produces_same_hash(self):
        a = ec.build_intent(**base_kwargs())
        b = ec.build_intent(**base_kwargs())
        self.assertEqual(a["intent_hash"], b["intent_hash"])

    def test_created_at_and_audit_id_do_not_affect_hash(self):
        a = ec.build_intent(**base_kwargs())
        b = ec.build_intent(**base_kwargs())
        self.assertNotEqual(a["created_at"], "")
        self.assertNotEqual(a["audit_id"], b["audit_id"])  # random UUIDs differ
        self.assertEqual(a["intent_hash"], b["intent_hash"])  # but hash is identical

    def test_quantity_change_alters_hash(self):
        a = ec.build_intent(**base_kwargs(quantity=100))
        b = ec.build_intent(**base_kwargs(quantity=200))
        self.assertNotEqual(a["intent_hash"], b["intent_hash"])

    def test_side_change_alters_hash(self):
        a = ec.build_intent(**base_kwargs(side="BUY"))
        b = ec.build_intent(**base_kwargs(side="SELL"))
        self.assertNotEqual(a["intent_hash"], b["intent_hash"])

    def test_symbol_change_alters_hash(self):
        a = ec.build_intent(**base_kwargs(symbol="285A.T"))
        b = ec.build_intent(**base_kwargs(symbol="8035.T"))
        self.assertNotEqual(a["intent_hash"], b["intent_hash"])

    def test_order_type_change_alters_hash(self):
        a = ec.build_intent(**base_kwargs(order_type="LIMIT", limit_price=1500.0))
        b = ec.build_intent(**base_kwargs(order_type="MARKET", limit_price=None))
        self.assertNotEqual(a["intent_hash"], b["intent_hash"])

    def test_limit_price_change_alters_hash(self):
        a = ec.build_intent(**base_kwargs(limit_price=1500.0))
        b = ec.build_intent(**base_kwargs(limit_price=1501.0))
        self.assertNotEqual(a["intent_hash"], b["intent_hash"])

    def test_strategy_version_change_alters_hash(self):
        a = ec.build_intent(**base_kwargs(strategy_version="1.0"))
        b = ec.build_intent(**base_kwargs(strategy_version="1.1"))
        self.assertNotEqual(a["intent_hash"], b["intent_hash"])

    def test_decision_snapshot_id_change_alters_hash(self):
        a = ec.build_intent(**base_kwargs(decision_snapshot_id="snap-1"))
        b = ec.build_intent(**base_kwargs(decision_snapshot_id="snap-2"))
        self.assertNotEqual(a["intent_hash"], b["intent_hash"])

    def test_execution_policy_version_change_alters_hash(self):
        a = ec.build_intent(**base_kwargs(execution_policy_version="exec-v0.1"))
        b = ec.build_intent(**base_kwargs(execution_policy_version="exec-v0.2"))
        self.assertNotEqual(a["intent_hash"], b["intent_hash"])

    def test_fields_outside_hash_spec_do_not_affect_hash(self):
        """planned_target/risk_policy_version/shadow_fill_model_version/signal_known_at
        はC-047のhash対象フィールド一覧に含まれないため、値を変えてもhashは変わらない。"""
        a = ec.build_intent(**base_kwargs(planned_target=1600.0, risk_policy_version="risk-v0.1",
                                            shadow_fill_model_version="shadow-v0.1",
                                            signal_known_at="2026-09-17T08:55:00+09:00"))
        b = ec.build_intent(**base_kwargs(planned_target=1999.0, risk_policy_version="risk-v9.9",
                                            shadow_fill_model_version="shadow-v9.9",
                                            signal_known_at="2026-09-17T09:00:00+09:00"))
        self.assertEqual(a["intent_hash"], b["intent_hash"])

    def test_block_reasons_order_does_not_affect_hash(self):
        """Golden #4: block_reasonsはそもそもhash対象外。可変後も再計算すれば同一hash。"""
        intent = ec.build_intent(**base_kwargs())
        original_hash = intent["intent_hash"]
        intent["block_reasons"] = ["RISK_LIMIT", "STALE_DATA"]
        self.assertEqual(ec.compute_intent_hash(intent), original_hash)
        intent["block_reasons"] = ["STALE_DATA", "RISK_LIMIT"]
        self.assertEqual(ec.compute_intent_hash(intent), original_hash)

    def test_key_order_does_not_affect_hash(self):
        payload_a = {"b": 2, "a": 1}
        payload_b = {"a": 1, "b": 2}
        self.assertEqual(ec._canonical_json(payload_a), ec._canonical_json(payload_b))


class DuplicateIntentTests(unittest.TestCase):
    def test_identical_intent_created_twice_is_flagged_duplicate(self):
        a = ec.build_intent(**base_kwargs())
        b = ec.build_intent(**base_kwargs())
        self.assertTrue(ec.is_duplicate_intent(b, [a]))

    def test_different_intent_is_not_duplicate(self):
        a = ec.build_intent(**base_kwargs(quantity=100))
        b = ec.build_intent(**base_kwargs(quantity=200))
        self.assertFalse(ec.is_duplicate_intent(b, [a]))

    def test_empty_existing_list_is_never_duplicate(self):
        a = ec.build_intent(**base_kwargs())
        self.assertFalse(ec.is_duplicate_intent(a, []))


class StatusTransitionTests(unittest.TestCase):
    def test_created_to_ticket_ready_allowed(self):
        self.assertEqual(ec.transition_status("CREATED", "TICKET_READY"), "TICKET_READY")

    def test_full_happy_path_sequence(self):
        sequence = ["CREATED", "TICKET_READY", "AUTHORIZED", "SUBMITTING", "ACKNOWLEDGED", "FILLED"]
        for current, target in zip(sequence, sequence[1:]):
            self.assertEqual(ec.transition_status(current, target), target)

    def test_created_to_filled_directly_is_rejected(self):
        with self.assertRaises(ValueError):
            ec.transition_status("CREATED", "FILLED")

    def test_ticket_ready_to_submitting_skips_authorized_and_is_rejected(self):
        with self.assertRaises(ValueError):
            ec.transition_status("TICKET_READY", "SUBMITTING")

    def test_unknown_has_no_outgoing_transitions(self):
        """Golden #10: UNKNOWN状態から自動再送を示す遷移は存在しない。"""
        self.assertEqual(ec.ALLOWED_TRANSITIONS["UNKNOWN"], frozenset())
        for target in ec.INTENT_STATUSES:
            with self.assertRaises(ValueError):
                ec.transition_status("UNKNOWN", target)

    def test_terminal_states_have_no_outgoing_transitions(self):
        for terminal in ("FILLED", "CANCELLED", "REJECTED", "RISK_BLOCKED", "PERMISSION_BLOCKED"):
            self.assertEqual(ec.ALLOWED_TRANSITIONS[terminal], frozenset())

    def test_unknown_target_status_rejected(self):
        with self.assertRaises(ValueError):
            ec.transition_status("CREATED", "SUBMITTED")  # not a real status in this vocabulary

    def test_submitting_can_resolve_to_unknown_on_comms_failure(self):
        self.assertEqual(ec.transition_status("SUBMITTING", "UNKNOWN"), "UNKNOWN")


class RealSubmitAllowedHardFixedTests(unittest.TestCase):
    def test_real_submit_allowed_is_always_false_in_output(self):
        for side in ("BUY", "SELL"):
            intent = ec.build_intent(**base_kwargs(side=side))
            self.assertIs(intent["real_submit_allowed"], False)

    def test_cannot_be_flipped_by_mutating_and_rehashing(self):
        """real_submit_allowedを後から書き換えてもintent_hashの対象フィールドには
        含まれていないため、hashの正当性検証だけではこの改ざんを検出できない、という
        設計上の限界を明示しておく——だからこそこの値はbuild_intent()の引数として
        一切受け付けず、生成時点で常にFalseに固定している。"""
        intent = ec.build_intent(**base_kwargs())
        original_hash = intent["intent_hash"]
        intent["real_submit_allowed"] = True  # 呼び出し側が辞書を直接書き換えた想定
        self.assertEqual(ec.compute_intent_hash(intent), original_hash)


if __name__ == "__main__":
    unittest.main()
