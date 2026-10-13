import importlib.util
import math
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "ledger", Path(__file__).parents[1] / "scripts/strategy_expectancy_ledger.py"
)
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)


def trade(i, *, pnl, lane="VIRTUAL_SIGNAL", role="TEST", side="LONG", symbol="1000",
          hour=9, minute=20, fees=10, slippage=5, mfe=1.0, mae=0.4, **extra):
    clock = f"2026-10-13T{hour:02d}:{minute:02d}:00+09:00"
    row = {
        "evidence_lane": lane,
        "strategy_id": "or15",
        "strategy_version": "1",
        "sample_role": role,
        "trade_id": f"t{i}",
        "pnl_yen": pnl,
        "fees": fees,
        "slippage": slippage,
        "signal_known_at": clock,
        "exit_known_at": f"2026-10-13T{hour:02d}:{minute:02d}:30+09:00",
        "sequence_time": clock,
        "window_start": "2026-10-01T00:00:00+09:00",
        "window_end": "2026-10-31T23:59:59+09:00",
        "universe_fixed_before_outcome": True,
        "side": side,
        "symbol": symbol,
        "entry_time": f"{hour:02d}:{minute:02d}",
        "mfe": mfe,
        "mae": mae,
        "real_submit_allowed": True,
    }
    row.update(extra)
    return row


def cohort(n=30):
    rows = []
    for i in range(n):
        minute = 20 + (i % 5)
        hour = 9 + (i // 5)
        rows.append(trade(
            i,
            pnl=100 if i % 3 else -50,
            side="SHORT" if i % 2 else "LONG",
            symbol="1000" if i % 2 else "2000",
            hour=hour,
            minute=minute,
        ))
    return rows


class ContractTests(unittest.TestCase):
    def test_complete_test_cohort_meets_measurement_contract_only(self):
        out = ledger.measure(cohort())
        self.assertEqual(out["status"], "MEASURED")
        self.assertEqual(out["evidence_lane"], "VIRTUAL_SIGNAL")
        self.assertTrue(out["expectancy_demonstrated"])
        self.assertFalse(out["promotion_eligible"])
        self.assertFalse(out["real_submit_allowed"])
        self.assertEqual(out["integrity"], [])
        metrics = out["metrics"]
        self.assertEqual(metrics["trade_count"]["value"], 30)
        self.assertAlmostEqual(metrics["expectancy_per_trade"]["value"], (20 * 85 + 10 * -65) / 30)
        self.assertLess(metrics["expectancy_per_trade"]["value"], metrics["gross_expectancy_per_trade"]["value"])
        self.assertEqual(out["by_side"].keys(), {"LONG", "SHORT"})
        self.assertEqual(set(out["by_symbol"]), {"1000", "2000"})
        self.assertIn("AM_0915", out["by_time_bucket"])
        self.assertEqual(out["mfe_mean"]["status"], "MEASURED")
        self.assertEqual(out["mae_mean"]["status"], "MEASURED")

    def test_sample_below_30_is_not_demonstrated(self):
        out = ledger.measure(cohort(29))
        self.assertFalse(out["expectancy_demonstrated"])
        self.assertIn("INSUFFICIENT_SAMPLE", out["integrity"])
        self.assertEqual(out["metrics"]["trade_count"]["value"], 29)

    def test_real_and_virtual_are_not_blended(self):
        rows = [trade(1, pnl=100), trade(2, pnl=-40, lane="REAL_FILL", role="REAL")]
        out = ledger.measure(rows)
        self.assertEqual(out["reason"], "MIXED_EVIDENCE_LANES")
        self.assertIsNone(out["metrics"])
        self.assertFalse(out["expectancy_demonstrated"])
        self.assertEqual(set(out["by_lane"]), {"REAL_FILL", "VIRTUAL_SIGNAL"})
        self.assertEqual(out["by_lane"]["REAL_FILL"]["evidence_lane"], "REAL_FILL")
        self.assertEqual(out["by_lane"]["VIRTUAL_SIGNAL"]["sample_role"], "TEST")

    def test_missing_fees_are_not_treated_as_zero(self):
        rows = cohort(1)
        rows[0]["fees"] = None
        out = ledger.measure(rows)
        self.assertEqual(out["included_n"], 0)
        self.assertIn("INCOMPLETE_COST_OR_PNL", out["integrity"])
        self.assertFalse(out["expectancy_demonstrated"])

    def test_duplicate_fill_is_excluded(self):
        rows = cohort(2)
        rows[1]["trade_id"] = rows[0]["trade_id"]
        out = ledger.measure(rows)
        self.assertEqual(out["included_n"], 0)
        self.assertIn("DUPLICATE_FILL", out["integrity"])

    def test_lookahead_and_undeclared_survivorship_block_demonstration(self):
        early = cohort(30)
        early[0]["exit_known_at"] = "2026-10-13T09:00:00+09:00"
        self.assertIn("LOOKAHEAD", ledger.measure(early)["integrity"])
        blind = cohort(30)
        blind[0]["universe_fixed_before_outcome"] = False
        blocked = ledger.measure(blind)
        self.assertIn("SURVIVORSHIP_UNDECLARED", blocked["integrity"])
        self.assertFalse(blocked["expectancy_demonstrated"])

    def test_legacy_paper_row_is_not_a_demonstrated_expectancy(self):
        legacy = {
            "date": "2026-07-28",
            "ticker": "6301.T",
            "side": "LONG",
            "triggered": True,
            "pnl_yen": 12500,
            "r": 1.19,
        }
        out = ledger.measure([legacy])
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "EVIDENCE_LANE_INVALID")
        self.assertFalse(out["expectancy_demonstrated"])
        self.assertFalse(out["real_submit_allowed"])

    def test_train_and_test_are_not_blended(self):
        rows = cohort(2)
        rows[1]["sample_role"] = "TRAIN"
        out = ledger.measure(rows)
        self.assertEqual(out["reason"], "MIXED_SAMPLE_ROLES")
        self.assertIsNone(out["metrics"])
        self.assertEqual(set(out["by_sample_role"]), {"TEST", "TRAIN"})

    def test_real_lane_rejects_backtest_role(self):
        out = ledger.measure([trade(1, pnl=100, lane="REAL_FILL", role="TRAIN")])
        self.assertEqual(out["reason"], "LANE_ROLE_MISMATCH")
        self.assertFalse(out["real_submit_allowed"])

    def test_no_losses_does_not_invent_infinite_profit_factor(self):
        out = ledger.measure([trade(1, pnl=100)])
        self.assertEqual(out["metrics"]["profit_factor"]["status"], "NOT_MEASURABLE")
        self.assertIsNone(out["metrics"]["profit_factor"]["value"])
        self.assertFalse(math.isinf(out["metrics"]["profit_factor"]["value"] or 0))
        self.assertIn("NO_LOSING_TRADES", out["integrity"])

    def test_unordered_sequence_hides_drawdown(self):
        rows = cohort(2)
        rows[0]["sequence_time"] = "2026-10-13T10:00:00+09:00"
        rows[1]["sequence_time"] = "2026-10-13T09:30:00+09:00"
        out = ledger.measure(rows)
        self.assertEqual(out["metrics"]["max_drawdown"]["status"], "NOT_MEASURABLE")
        self.assertIn("SEQUENCE_NOT_MONOTONIC", out["integrity"])

    def test_named_session_buckets(self):
        specs = [
            (9, 0, "OPEN_0900"),
            (9, 15, "AM_0915"),
            (9, 30, "AM_0930"),
            (10, 0, "AM_1000"),
            (10, 30, "AM_1030"),
            (11, 0, "AM_1100"),
            (12, 30, "OPEN_1230"),
            (13, 0, "PM_1300"),
            (14, 0, "PM_1400"),
            (14, 30, "PM_1430"),
            (15, 0, "CLOSE_1500"),
            (11, 30, "OUT_OF_NAMED_SESSION"),
        ]
        rows = [trade(i, pnl=100 if i else -10, hour=hour, minute=minute) for i, (hour, minute, _) in enumerate(specs)]
        out = ledger.measure(rows)
        self.assertEqual([out["by_time_bucket"][name]["trade_count"]["value"] for _, _, name in specs], [1] * len(specs))


if __name__ == "__main__":
    unittest.main()
