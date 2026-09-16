import importlib.util
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[1] / 'scripts/risk_gate.py'
spec = importlib.util.spec_from_file_location('rg', SCRIPT_PATH)
rg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rg)

POLICY = {
    "policy_version": "risk-gate-0.1.0",
    "test_capital_yen": 300000,
    "risk_per_trade_pct": 0.0025,
    "risk_per_trade_yen": 750,
    "daily_stop_yen": 3000,
    "max_open_positions": 1,
    "account_mode": "CASH",
    "allow_averaging_down": False,
    "allow_flip": False,
    "allow_pyramiding": False,
    "allow_margin_leverage": False,
}


def scenario(symbol="285A.T", side="BUY", horizon="day", merge_hash="a" * 64,
             resolved_status="CANDIDATE_READY", entry=1000.0, stop=995.0,
             confirming_strategy_ids=None, **extra):
    return {
        "symbol": symbol, "side": side, "horizon": horizon, "merge_hash": merge_hash,
        "resolved_status": resolved_status, "entry": entry, "stop": stop,
        "confirming_strategy_ids": confirming_strategy_ids or [],
        **extra,
    }


def evaluate(sc=None, *, cash=300000.0, open_positions=0, pnl_today=0.0, multiplier=1.0,
             fees=100.0, lot_size=100, policy=None):
    return rg.evaluate_risk(
        sc if sc is not None else scenario(), available_cash_yen=cash,
        open_positions_count=open_positions, realized_pnl_today_yen=pnl_today,
        regime_risk_multiplier=multiplier, estimated_fees_buffer_yen=fees,
        lot_size=lot_size, policy=policy or POLICY,
    )


class SizingGoldenTests(unittest.TestCase):
    def test_golden_1_risk_per_lot_exceeds_budget_is_shadow_only(self):
        """Golden #1: BUY 3000/stop 2980/lot100 -> risk_per_lot=2000>750 -> SHADOW_ONLY, qty=0."""
        out = evaluate(scenario(entry=3000.0, stop=2980.0))
        self.assertEqual(out["decision"], "SHADOW_ONLY")
        self.assertEqual(out["allowed_qty"], 0)
        self.assertIn("RISK_BUDGET_EXCEEDED", out["block_reasons"])

    def test_golden_2_valid_sizing_passes_with_qty_100(self):
        """Golden #2: BUY 1000/stop 995/lot100/cash充分/mult1.0 -> qty=100, PASS."""
        out = evaluate(scenario(entry=1000.0, stop=995.0), cash=300000.0, multiplier=1.0)
        self.assertEqual(out["decision"], "PASS")
        self.assertEqual(out["allowed_qty"], 100)

    def test_golden_3_insufficient_cash_is_shadow_only(self):
        """Golden #3: risk上OKでもcash不足 -> SHADOW_ONLY, qty=0."""
        out = evaluate(scenario(entry=1000.0, stop=995.0), cash=1000.0)
        self.assertEqual(out["decision"], "SHADOW_ONLY")
        self.assertEqual(out["allowed_qty"], 0)
        self.assertIn("INSUFFICIENT_CASH", out["block_reasons"])

    def test_golden_4_daily_stop_reached_is_shadow_only(self):
        """Golden #4: realized P/L=-3000 -> daily stopでSHADOW_ONLY, qty=0."""
        out = evaluate(scenario(), pnl_today=-3000.0)
        self.assertEqual(out["decision"], "SHADOW_ONLY")
        self.assertEqual(out["allowed_qty"], 0)
        self.assertIn("DAILY_STOP_REACHED", out["block_reasons"])

    def test_golden_5_max_open_positions_reached_is_shadow_only(self):
        """Golden #5: open_positions_count=1 -> SHADOW_ONLY, qty=0。"""
        out = evaluate(scenario(), open_positions=1)
        self.assertEqual(out["decision"], "SHADOW_ONLY")
        self.assertEqual(out["allowed_qty"], 0)
        self.assertIn("MAX_OPEN_POSITIONS_REACHED", out["block_reasons"])

    def test_golden_6_multiplier_half_gives_375_budget(self):
        """Golden #6: multiplier 0.5 -> risk budget=375。"""
        out = evaluate(scenario(), multiplier=0.5)
        self.assertEqual(out["risk_budget_yen"], 375.0)

    def test_golden_7_multiplier_above_one_does_not_expand_budget(self):
        """Golden #7: multiplier 2.0 -> 750を超えて拡大しない。"""
        out = evaluate(scenario(), multiplier=2.0)
        self.assertEqual(out["risk_budget_yen"], 750.0)

    def test_multiplier_zero_gives_zero_budget_and_shadow_only(self):
        out = evaluate(scenario(), multiplier=0.0)
        self.assertEqual(out["risk_budget_yen"], 0.0)
        self.assertEqual(out["decision"], "SHADOW_ONLY")
        self.assertEqual(out["allowed_qty"], 0)


class BlockValidationTests(unittest.TestCase):
    def test_golden_8_invalid_lot_size_blocks(self):
        """Golden #8: lot_size None/0/負値 -> BLOCK。"""
        for bad_lot in (None, 0, -100):
            out = evaluate(lot_size=bad_lot)
            self.assertEqual(out["decision"], "BLOCK", msg=f"lot_size={bad_lot}")
            self.assertIn("LOT_SIZE_INVALID", out["block_reasons"])

    def test_golden_9_entry_equals_stop_blocks(self):
        """Golden #9: entry==stop -> BLOCK。"""
        out = evaluate(scenario(entry=1000.0, stop=1000.0))
        self.assertEqual(out["decision"], "BLOCK")
        self.assertIn("BLOCK_INVALID_STOP_DIRECTION", out["block_reasons"])

    def test_golden_10_wrong_direction_stop_blocks(self):
        """Golden #10: BUYでstop>=entry / SELLでstop<=entry -> BLOCK_INVALID_STOP_DIRECTION。"""
        buy_wrong = evaluate(scenario(side="BUY", entry=1000.0, stop=1010.0))
        self.assertEqual(buy_wrong["decision"], "BLOCK")
        self.assertIn("BLOCK_INVALID_STOP_DIRECTION", buy_wrong["block_reasons"])

        sell_wrong = evaluate(scenario(side="SELL", entry=1000.0, stop=990.0))
        self.assertEqual(sell_wrong["decision"], "BLOCK")
        self.assertIn("BLOCK_INVALID_STOP_DIRECTION", sell_wrong["block_reasons"])

    def test_golden_11_malformed_numeric_inputs_block(self):
        """Golden #11: malformed/NaN/inf inputs -> BLOCK。"""
        nan, inf = float("nan"), float("inf")
        cases = [
            dict(sc=scenario(entry=nan)),
            dict(sc=scenario(entry=inf)),
            dict(sc=scenario(stop=nan)),
            dict(cash=nan),
            dict(pnl_today=nan),
            dict(multiplier=nan),
            dict(multiplier=-1.0),
            dict(fees=nan),
            dict(fees=-1.0),
        ]
        for kwargs in cases:
            out = evaluate(**kwargs)
            self.assertEqual(out["decision"], "BLOCK", msg=f"case={kwargs}")

    def test_golden_12_non_candidate_ready_blocks(self):
        """Golden #12: resolved_status != CANDIDATE_READY -> BLOCK。"""
        for status in ("MERGED_CONFIRMATION", "CONFLICT_BLOCKED_OPPOSITE_SIDE",
                       "BLOCKED_DATA_QUALITY", "BLOCKED_MAX_OPEN_POSITIONS",
                       "BLOCKED_DUPLICATE_ORDER", "BLOCKED_SESSION_MISMATCH"):
            out = evaluate(scenario(resolved_status=status))
            self.assertEqual(out["decision"], "BLOCK", msg=f"status={status}")
            self.assertIn("RESOLVED_STATUS_NOT_CANDIDATE_READY", out["block_reasons"])

    def test_golden_13_missing_or_empty_horizon_blocks(self):
        """Golden #13: horizon欠損/None/空 -> BLOCK。"""
        for bad_horizon in (None, ""):
            out = evaluate(scenario(horizon=bad_horizon))
            self.assertEqual(out["decision"], "BLOCK", msg=f"horizon={bad_horizon!r}")
            self.assertIn("HORIZON_MISSING", out["block_reasons"])
        sc_no_horizon = scenario()
        del sc_no_horizon["horizon"]
        out = evaluate(sc_no_horizon)
        self.assertEqual(out["decision"], "BLOCK")


class ConfirmationDoesNotAffectSizingTests(unittest.TestCase):
    def test_golden_14_confirming_strategies_do_not_change_risk_budget(self):
        """Golden #14: same-side confirmationが増えてもrisk budgetは750円のまま。"""
        no_confirmations = evaluate(scenario(confirming_strategy_ids=[]))
        many_confirmations = evaluate(scenario(
            confirming_strategy_ids=["day_rank_long", "day_short_mvp", "x", "y", "z"]))
        self.assertEqual(no_confirmations["risk_budget_yen"], many_confirmations["risk_budget_yen"])
        self.assertEqual(no_confirmations["allowed_qty"], many_confirmations["allowed_qty"])


class NoIntentHashTests(unittest.TestCase):
    def test_golden_15_no_canonical_intent_hash_in_output_or_used_as_input(self):
        """Golden #15: Phase 3 input/outputにcanonical intent_hashを要求・生成しない。"""
        sc = scenario()
        self.assertNotIn("intent_hash", sc)  # scenario自体もintent_hashを持たない前提
        out = evaluate(sc)
        self.assertNotIn("intent_hash", out)
        self.assertIn("merge_hash", out)
        self.assertEqual(out["merge_hash"], sc["merge_hash"])


class RealSubmitAllowedAbsentTests(unittest.TestCase):
    def test_golden_16_real_submit_allowed_never_present(self):
        """Golden #16: Risk Gate出力にreal_submit_allowed=Trueが存在しない
        （そもそもキー自体を作らない）。"""
        for sc in (scenario(), scenario(resolved_status="BLOCKED_DATA_QUALITY"),
                   scenario(entry=1000.0, stop=1000.0)):
            out = evaluate(sc)
            self.assertNotIn("real_submit_allowed", out)


class CashModeTests(unittest.TestCase):
    def test_golden_17_cash_mode_new_sell_is_shadow_only(self):
        """Golden #17: CASH modeの新規SELL -> SHADOW_ONLY。"""
        out = evaluate(scenario(side="SELL", entry=1000.0, stop=1010.0))
        self.assertEqual(out["decision"], "SHADOW_ONLY")
        self.assertEqual(out["allowed_qty"], 0)
        self.assertIn("CASH_MODE_NO_SHORT", out["block_reasons"])


class DeterminismTests(unittest.TestCase):
    def test_golden_18_same_input_gives_same_decision_ignoring_wall_clock(self):
        """Golden #18: 同一入力は同一RiskDecision（wall-clock値を判定に混ぜない）。"""
        out_a = evaluate(scenario())
        out_b = evaluate(scenario())
        strip = lambda d: {k: v for k, v in d.items() if k != "generated_at"}
        self.assertEqual(strip(out_a), strip(out_b))


class NoBrokerReferenceTests(unittest.TestCase):
    def test_golden_19_no_broker_rss_or_network_references(self):
        import ast
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
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


class DoesNotTouchOtherSafetyFlagsTests(unittest.TestCase):
    def test_golden_20_does_not_import_signal_contract_or_execution_contract(self):
        """Golden #20: signal_contract.pyのtrading_enabled=False、execution_contract.pyの
        real_submit_allowed=Falseを変更しない——risk_gate.pyがそれらのモジュールを
        importすらしていないことで、変更する経路自体が無いことを証明する。"""
        import ast
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        self.assertNotIn("signal_contract", imported_modules)
        self.assertNotIn("execution_contract", imported_modules)

    def test_source_files_still_have_hard_fixed_false_flags(self):
        signal_contract_src = (SCRIPT_PATH.parent / "signal_contract.py").read_text(encoding="utf-8")
        execution_contract_src = (SCRIPT_PATH.parent / "execution_contract.py").read_text(encoding="utf-8")
        self.assertIn('"trading_enabled": False', signal_contract_src)
        self.assertIn('"real_submit_allowed": False', execution_contract_src)


class CashCapTests(unittest.TestCase):
    """Phase 3.1 Blocker 1: test_capital_yen（30万円）をnotional上限として効かせる。"""

    def test_golden_21_notional_plus_fees_never_exceeds_test_capital(self):
        """Golden #21: available_cash=1,000,000円でもnotional+feesが300,000円を超えない。"""
        entry = 500.0
        out = evaluate(scenario(entry=entry, stop=499.0), cash=1_000_000.0, fees=100.0)
        self.assertEqual(out["decision"], "PASS")
        notional = out["allowed_qty"] * entry
        self.assertLessEqual(notional + 100.0, 300000)

    def test_golden_22_large_cash_does_not_bypass_300k_cap(self):
        """Golden #22: entry=500/stop=499/lot100/cash=1,000,000 -> 700株ではなく
        30万円cap内の最大数量だけPASS。"""
        out = evaluate(scenario(entry=500.0, stop=499.0), cash=1_000_000.0, fees=100.0)
        self.assertEqual(out["decision"], "PASS")
        self.assertNotEqual(out["allowed_qty"], 700)  # cashのみで計算した場合の(誤った)値
        self.assertEqual(out["allowed_qty"], 500)  # test_capitalでcapされた正しい値
        self.assertLessEqual(out["allowed_qty"] * 500.0 + 100.0, 300000)


class PolicyValidationTests(unittest.TestCase):
    """Phase 3.1 Blocker 2: 壊れた/未対応のv0.1 policyをfail closedにする。"""

    def test_golden_23_unsupported_account_mode_blocks(self):
        for mode in ("MARGIN", "UNKNOWN", None, ""):
            out = evaluate(policy={**POLICY, "account_mode": mode})
            self.assertEqual(out["decision"], "BLOCK", msg=f"account_mode={mode!r}")
            self.assertIn("BLOCK_POLICY_UNSUPPORTED_ACCOUNT_MODE", out["block_reasons"])

    def test_golden_24_margin_leverage_true_blocks(self):
        out = evaluate(policy={**POLICY, "allow_margin_leverage": True})
        self.assertEqual(out["decision"], "BLOCK")
        self.assertIn("BLOCK_POLICY_MARGIN_LEVERAGE_NOT_ALLOWED", out["block_reasons"])

    def test_golden_25_unsafe_trade_mode_flags_block(self):
        for flag in ("allow_averaging_down", "allow_flip", "allow_pyramiding"):
            out = evaluate(policy={**POLICY, flag: True})
            self.assertEqual(out["decision"], "BLOCK", msg=f"{flag}=True")

    def test_golden_26_missing_or_invalid_policy_numeric_fields_block_not_raise(self):
        """Golden #26: policy必須key欠損/NaN/負値はexceptionではなくBLOCKで返す。"""
        broken_policies = [
            {k: v for k, v in POLICY.items() if k != "test_capital_yen"},  # missing key
            {**POLICY, "risk_per_trade_yen": float("nan")},
            {**POLICY, "daily_stop_yen": -3000},
            {**POLICY, "max_open_positions": 0},
            {**POLICY, "max_open_positions": 1.5},
            {**POLICY, "max_open_positions": None},
        ]
        for bad_policy in broken_policies:
            try:
                out = evaluate(policy=bad_policy)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"evaluate_risk raised {exc!r} for policy={bad_policy} instead of returning BLOCK")
            self.assertEqual(out["decision"], "BLOCK", msg=f"policy={bad_policy}")


class ScenarioAndSnapshotValidationTests(unittest.TestCase):
    """Phase 3.1 Blocker 3: symbol/merge_hash/available_cash/open_positions_countの検証。"""

    def test_golden_27_empty_symbol_or_merge_hash_blocks(self):
        out_symbol = evaluate(scenario(symbol=""))
        self.assertEqual(out_symbol["decision"], "BLOCK")
        self.assertIn("BLOCK_SYMBOL_INVALID", out_symbol["block_reasons"])

        out_merge_hash = evaluate(scenario(merge_hash=""))
        self.assertEqual(out_merge_hash["decision"], "BLOCK")
        self.assertIn("BLOCK_MERGE_HASH_INVALID", out_merge_hash["block_reasons"])

        out_none = evaluate(scenario(symbol=None))
        self.assertEqual(out_none["decision"], "BLOCK")

    def test_golden_28_negative_available_cash_blocks(self):
        out = evaluate(cash=-1.0)
        self.assertEqual(out["decision"], "BLOCK")
        self.assertIn("BLOCK_AVAILABLE_CASH_INVALID", out["block_reasons"])

    def test_golden_29_non_integer_or_invalid_open_positions_count_blocks(self):
        for bad_count in (0.5, -1, float("nan"), float("inf")):
            out = evaluate(open_positions=bad_count)
            self.assertEqual(out["decision"], "BLOCK", msg=f"open_positions_count={bad_count}")
            self.assertIn("OPEN_POSITIONS_COUNT_INVALID", out["block_reasons"])


class Phase31NoRegressionTests(unittest.TestCase):
    def test_golden_30_canonical_policy_golden_1_and_2_still_pass(self):
        """Golden #30: normal canonical policy + Golden #1〜20は回帰しない
        （代表として#1と#2だけここでも再確認し、詳細は既存テストクラス群が担保する）。"""
        shadow = evaluate(scenario(entry=3000.0, stop=2980.0))
        self.assertEqual(shadow["decision"], "SHADOW_ONLY")
        passed = evaluate(scenario(entry=1000.0, stop=995.0))
        self.assertEqual(passed["decision"], "PASS")
        self.assertEqual(passed["allowed_qty"], 100)


class LoadPolicyTests(unittest.TestCase):
    def test_default_policy_file_loads_and_matches_v0_1_fixed_values(self):
        policy = rg.load_policy()
        self.assertEqual(policy["policy_version"], "risk-gate-0.1.0")
        self.assertEqual(policy["test_capital_yen"], 300000)
        self.assertEqual(policy["risk_per_trade_yen"], 750)
        self.assertEqual(policy["daily_stop_yen"], 3000)
        self.assertEqual(policy["max_open_positions"], 1)
        self.assertEqual(policy["account_mode"], "CASH")
        self.assertFalse(policy["allow_margin_leverage"])


if __name__ == "__main__":
    unittest.main()
