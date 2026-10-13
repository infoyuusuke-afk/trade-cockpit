import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = _load("paper_history_expectancy_adapter", "scripts/paper_history_expectancy_adapter.py")
ledger = _load("strategy_expectancy_ledger_for_adapter", "scripts/strategy_expectancy_ledger.py")


def paper(**extra):
    row = {
        "evidence_lane": "VIRTUAL_SIGNAL",
        "strategy_id": "day_ifo_long",
        "strategy_version": "1.0",
        "sample_role": "TEST",
        "trade_id": "t",
        "symbol": "285A",
        "side": "LONG",
        "signal_known_at": "2026-10-13T09:00:00+09:00",
        "entry_time": "09:00",
        "exit_known_at": "2026-10-13T09:00:30+09:00",
        "sequence_time": "2026-10-13T09:00:00+09:00",
        "pnl_yen": 100,
        "fees": 10,
        "slippage": 5,
        "mfe": 1.0,
        "mae": 0.4,
        "window_start": "2026-10-01T00:00:00+09:00",
        "window_end": "2026-10-31T23:59:59+09:00",
        "universe_fixed_before_outcome": True,
        "real_submit_allowed": True,
        "promotion_eligible": True,
    }
    row.update(extra)
    return row


def cohort(n=30, **extra):
    rows = []
    for i in range(n):
        clock = f"2026-10-13T09:{i:02d}:00+09:00"
        rows.append(paper(
            trade_id=f"t{i:03d}",
            pnl_yen=100 if i % 3 else -50,
            side="SHORT" if i % 2 else "LONG",
            symbol="1000" if i % 2 else "2000",
            signal_known_at=clock,
            sequence_time=clock,
            exit_known_at=f"2026-10-13T09:{i:02d}:30+09:00",
            entry_time=f"09:{i:02d}",
            **extra,
        ))
    return rows


class AdapterTests(unittest.TestCase):
    def test_complete_virtual_cohort_is_measured(self):
        rows = cohort()
        out = adapter.connect(rows)
        self.assertEqual(out["status"], "MEASURED")
        self.assertIsNone(out["reason"])
        self.assertTrue(out["expectancy_demonstrated"])
        self.assertFalse(out["statistical_edge_confirmed"])
        self.assertFalse(out["promotion_eligible"])
        self.assertFalse(out["real_submit_allowed"])
        self.assertEqual(out["included_n"], 30)
        self.assertEqual(out["metrics"]["trade_count"]["value"], 30)
        self.assertAlmostEqual(out["metrics"]["expectancy_per_trade"]["value"], (20 * 85 + 10 * -65) / 30)
        self.assertLess(
            out["metrics"]["expectancy_per_trade"]["value"],
            out["metrics"]["gross_expectancy_per_trade"]["value"],
        )
        self.assertEqual(out["ledger"]["status"], "MEASURED")
        direct = ledger.measure(out["projected"])
        self.assertEqual(
            direct["metrics"]["expectancy_per_trade"]["value"],
            out["metrics"]["expectancy_per_trade"]["value"],
        )
        self.assertNotIn("real_submit_allowed", out["projected"][0])
        self.assertNotIn("promotion_eligible", out["projected"][0])

    def test_missing_required_fields_are_blocked(self):
        for key, reason in (
            ("strategy_id", "STRATEGY_ID_INVALID"),
            ("sample_role", "SAMPLE_ROLE_INVALID"),
            ("evidence_lane", "EVIDENCE_LANE_INVALID"),
            ("trade_id", "MISSING_TRADE_ID"),
        ):
            rows = cohort(1)
            rows[0].pop(key)
            out = adapter.connect(rows)
            self.assertEqual(out["status"], "BLOCKED", key)
            self.assertFalse(out["expectancy_demonstrated"], key)
            self.assertIsNone(out["metrics"], key)
            if key == "trade_id":
                self.assertIn(reason, out["integrity"], key)
                self.assertEqual(out["reason"], reason, key)
            else:
                self.assertEqual(out["reason"], reason, key)

    def test_missing_fees_are_not_treated_as_zero(self):
        for missing in ("pop", None):
            rows = cohort(1)
            if missing == "pop":
                rows[0].pop("fees")
            else:
                rows[0]["fees"] = None
            before = copy.deepcopy(rows)
            out = adapter.connect(rows)
            self.assertEqual(rows, before, missing)
            self.assertNotIn("fees", out["projected"][0], missing)
            self.assertNotEqual(out["projected"][0].get("fees"), 0, missing)
            self.assertEqual(out["status"], "BLOCKED", missing)
            self.assertEqual(out["reason"], "INCOMPLETE_COST_OR_PNL", missing)
            self.assertFalse(out["expectancy_demonstrated"], missing)
            self.assertIsNone(out["metrics"], missing)
            self.assertEqual(out["included_n"], 0, missing)
            self.assertFalse(out["cost_zero_filled"], missing)

    def test_negative_cost_is_not_clamped_to_zero(self):
        rows = cohort(1)
        rows[0]["fees"] = -10
        out = adapter.connect(rows)
        self.assertEqual(out["projected"][0]["fees"], -10)
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "INCOMPLETE_COST_OR_PNL")
        self.assertFalse(out["expectancy_demonstrated"])

    def test_placeholder_zero_costs_are_withheld(self):
        rows = cohort(1)
        rows[0]["fees"] = 0
        rows[0]["slippage"] = 0
        out = adapter.connect(rows)
        self.assertNotIn("fees", out["projected"][0])
        self.assertNotIn("slippage", out["projected"][0])
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "INCOMPLETE_COST_OR_PNL")
        self.assertIn("FEES_UNVERIFIED_ZERO", out["projection_notes"][0]["reasons"])
        self.assertFalse(out["expectancy_demonstrated"])

    def test_verified_zero_cost_is_an_explicit_number(self):
        rows = cohort(cost_model_status="VERIFIED", fees=0, slippage=0)
        out = adapter.connect(rows)
        self.assertEqual(out["projected"][0]["fees"], 0)
        self.assertEqual(out["projected"][0]["slippage"], 0)
        self.assertEqual(out["status"], "MEASURED")
        self.assertTrue(out["expectancy_demonstrated"])
        self.assertFalse(out["statistical_edge_confirmed"])
        self.assertAlmostEqual(out["metrics"]["expectancy_per_trade"]["value"], (20 * 100 + 10 * -50) / 30)

    def test_duplicate_trade_is_blocked(self):
        rows = cohort(2)
        rows[1]["trade_id"] = rows[0]["trade_id"]
        out = adapter.connect(rows)
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "DUPLICATE_FILL")
        self.assertEqual(out["included_n"], 0)
        self.assertIsNone(out["metrics"])
        self.assertFalse(out["expectancy_demonstrated"])

    def test_lookahead_is_blocked(self):
        rows = cohort(1)
        rows[0]["exit_known_at"] = "2026-10-13T08:59:00+09:00"
        out = adapter.connect(rows)
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "LOOKAHEAD")
        self.assertFalse(out["expectancy_demonstrated"])
        self.assertIsNone(out["metrics"])

    def test_non_finite_pnl_is_blocked_and_not_replaced(self):
        rows = cohort(1)
        rows[0]["pnl_yen"] = float("nan")
        out = adapter.connect(rows)
        self.assertNotEqual(out["projected"][0]["pnl_yen"], 0)
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "INCOMPLETE_COST_OR_PNL")

    def test_display_timestamps_and_uppercase_excursions_are_not_rewritten(self):
        legacy = {
            "date": "2026-10-13",
            "ticker": "3132.T",
            "side": "LONG",
            "strategy_id": "day_rank_long",
            "strategy_version": "1.0",
            "signal_time": "2026-10-13 18:26:20 JST",
            "pnl_yen": 16500,
            "fees": 0,
            "slippage": 0,
            "MFE": 2.45,
            "MAE": 0.86,
            "source": "morning_snapshot",
        }
        original = copy.deepcopy(legacy)
        out = adapter.connect([legacy])
        self.assertEqual(legacy, original)
        projected = out["projected"][0]
        self.assertEqual(projected["symbol"], "3132.T")
        self.assertNotIn("evidence_lane", projected)
        self.assertNotIn("sample_role", projected)
        self.assertNotIn("signal_known_at", projected)
        self.assertNotIn("exit_known_at", projected)
        self.assertNotIn("mfe", projected)
        self.assertNotIn("mae", projected)
        self.assertNotIn("fees", projected)
        self.assertNotIn("slippage", projected)
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "EVIDENCE_LANE_INVALID")
        self.assertFalse(out["expectancy_demonstrated"])

    def test_strategy_key_is_not_copied_into_strategy_id(self):
        rows = cohort(1)
        rows[0].pop("strategy_id")
        rows[0]["strategy_key"] = "day_ifo_long"
        out = adapter.connect(rows)
        self.assertNotIn("strategy_id", out["projected"][0])
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "STRATEGY_ID_INVALID")

    def test_unknown_strategy_version_is_not_a_cohort(self):
        rows = cohort(1, strategy_version="unknown")
        out = adapter.connect(rows)
        self.assertNotIn("strategy_version", out["projected"][0])
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "STRATEGY_VERSION_INVALID")

    def test_real_and_virtual_are_not_blended(self):
        rows = [paper(trade_id="v1"), paper(trade_id="r1", evidence_lane="REAL_FILL", sample_role="REAL")]
        out = adapter.connect(rows)
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "MIXED_EVIDENCE_LANES")
        self.assertIsNone(out["metrics"])
        self.assertFalse(out["expectancy_demonstrated"])
        self.assertNotIn("by_lane", out)
        self.assertEqual(set(out["ledger"]["by_lane"]), {"REAL_FILL", "VIRTUAL_SIGNAL"})

    def test_train_test_and_shadow_are_not_blended(self):
        rows = [
            paper(trade_id="train", sample_role="TRAIN"),
            paper(trade_id="test", sample_role="TEST"),
            paper(trade_id="shadow", sample_role="SHADOW"),
        ]
        out = adapter.connect(rows)
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "MIXED_SAMPLE_ROLES")
        self.assertIsNone(out["metrics"])
        self.assertFalse(out["expectancy_demonstrated"])
        self.assertEqual(set(out["ledger"]["by_sample_role"]), {"TRAIN", "TEST", "SHADOW"})

    def test_sample_below_30_is_not_demonstrated(self):
        out = adapter.connect(cohort(29))
        self.assertEqual(out["status"], "MEASURED")
        self.assertFalse(out["expectancy_demonstrated"])
        self.assertFalse(out["statistical_edge_confirmed"])
        self.assertIn("INSUFFICIENT_SAMPLE", out["integrity"])
        self.assertEqual(out["metrics"]["trade_count"]["value"], 29)
        self.assertFalse(out["promotion_eligible"])
        self.assertFalse(out["real_submit_allowed"])

    def test_same_input_produces_the_same_result(self):
        rows = cohort()
        first = json.dumps(adapter.connect(rows), ensure_ascii=False, sort_keys=True)
        second = json.dumps(adapter.connect(copy.deepcopy(rows)), ensure_ascii=False, sort_keys=True)
        self.assertEqual(first, second)

    def test_input_and_history_file_are_unchanged(self):
        path = ROOT / "paper_trade_history.json"
        before = path.read_bytes()
        records = json.loads(before.decode("utf-8-sig"))
        snapshot = copy.deepcopy(records)
        adapter.connect(records)
        self.assertEqual(records, snapshot)
        out = adapter.connect_file(path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(records, snapshot)
        self.assertTrue(out["source_unchanged"])
        self.assertFalse(out["source_mutated"])
        self.assertEqual(out["records_examined"], len(records))
        self.assertTrue(any("evidence_lane" not in row for row in records))
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "EVIDENCE_LANE_INVALID")
        self.assertFalse(out["expectancy_demonstrated"])
        self.assertFalse(out["statistical_edge_confirmed"])
        self.assertFalse(out["real_submit_allowed"])
        self.assertFalse(out["promotion_eligible"])
        self.assertEqual(out["included_n"], 0)
        self.assertIsNone(out["metrics"])
        for src, proj in zip(records, out["projected"]):
            self.assertNotIn("evidence_lane", proj)
            self.assertNotIn("sample_role", proj)
            if src.get("cost_model_status") != "VERIFIED":
                fees = src.get("fees")
                slip = src.get("slippage")
                if not isinstance(fees, (int, float)) or isinstance(fees, bool) or fees <= 0:
                    self.assertNotIn("fees", proj)
                if not isinstance(slip, (int, float)) or isinstance(slip, bool) or slip <= 0:
                    self.assertNotIn("slippage", proj)
        again = json.dumps(adapter.connect_file(path), ensure_ascii=False, sort_keys=True)
        self.assertEqual(again, json.dumps(out, ensure_ascii=False, sort_keys=True))
        self.assertEqual(path.read_bytes(), before)

    def test_missing_universe_is_not_assumed_fixed(self):
        rows = cohort(1)
        rows[0].pop("universe_fixed_before_outcome")
        out = adapter.connect(rows)
        self.assertNotIn("universe_fixed_before_outcome", out["projected"][0])
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], "SURVIVORSHIP_UNDECLARED")


if __name__ == "__main__":
    unittest.main()
