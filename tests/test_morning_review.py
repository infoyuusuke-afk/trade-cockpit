import importlib.util
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location('mr', Path(__file__).parents[1] / 'scripts/morning_review.py')
mr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)

JST = ZoneInfo("Asia/Tokyo")


def plan(side="LONG", entry=100, stop=95, target1=110, target2=120, **extra):
    return {"name": "テスト", "side": side, "entry": entry, "entry_limit": entry,
            "stop": stop, "target1": target1, "target2": target2, **extra}


class AuditOneTests(unittest.TestCase):
    def test_stop_hit_tags_exit_reason_and_mfe_mae(self):
        stock = {"intraday": {"low": 90, "high": 105, "close": 95, "vwap": 100}}
        result = mr.audit_one(plan(), stock)
        self.assertEqual(result["result"], "IFO損切り")
        self.assertEqual(result["exit_reason"], "STOP")
        self.assertTrue(result["triggered"])
        self.assertIsNotNone(result["MFE"])
        self.assertIsNotNone(result["MAE"])
        self.assertEqual(result["R"], result["r"])

    def test_not_triggered_has_no_mfe_mae(self):
        stock = {"intraday": {"low": 96, "high": 99, "close": 98, "vwap": 98}}
        result = mr.audit_one(plan(entry=100, stop=95), stock)
        self.assertFalse(result["triggered"])
        self.assertIsNone(result["MFE"])
        self.assertIsNone(result["MAE"])
        self.assertEqual(result["exit_reason"], "NOT_TRIGGERED")

    def test_entry_trigger_and_simulated_fill_are_set(self):
        stock = {"intraday": {"low": 90, "high": 105, "close": 102, "vwap": 100}}
        result = mr.audit_one(plan(), stock)
        self.assertEqual(result["entry_trigger"], 100)
        self.assertEqual(result["simulated_fill"], 100)
        self.assertEqual(result["fees"], 0)
        self.assertEqual(result["slippage"], 0)

    def test_existing_fields_from_plan_survive(self):
        stock = {"intraday": {"low": 90, "high": 105, "close": 102, "vwap": 100}}
        result = mr.audit_one(plan(strategy_id="day_ifo_long"), stock)
        self.assertEqual(result["strategy_id"], "day_ifo_long")


class MorningSnapshotTests(unittest.TestCase):
    def setUp(self):
        # load_short_candidates() reads mr.SHORT_CANDIDATES from the real filesystem;
        # redirect it to a path that doesn't exist so these tests don't depend on
        # whatever day_ifo_candidates_short.json happens to contain on the day the
        # suite runs (load() falls back to {} on FileNotFoundError).
        self._orig_short_path = mr.SHORT_CANDIDATES
        mr.SHORT_CANDIDATES = Path("/nonexistent/day_ifo_candidates_short.json")

    def tearDown(self):
        mr.SHORT_CANDIDATES = self._orig_short_path

    def test_day_ifo_candidates_get_day_ifo_long_strategy_id(self):
        data = {"day_ifo_candidates": [
            {"name": "A", "ticker": "1111.T", "side": "LONG", "score": 80,
             "trigger": 100, "entry_limit": 100, "stop": 95, "target1": 110, "target2": 120},
        ]}
        snap = mr.morning_snapshot(data, datetime(2026, 9, 17, 8, 55, tzinfo=JST))
        self.assertEqual(len(snap["candidates"]), 1)
        self.assertEqual(snap["candidates"][0]["strategy_id"], "day_ifo_long")

    def test_falls_back_to_day_rank_long_when_no_ifo_candidates(self):
        data = {"day_candidates": [
            {"name": "B", "ticker": "2222.T", "side": "LONG", "score": 80,
             "trigger": 100, "entry_limit": 100, "stop": 95, "target1": 110, "target2": 120},
        ]}
        snap = mr.morning_snapshot(data, datetime(2026, 9, 17, 8, 55, tzinfo=JST))
        self.assertEqual(snap["candidates"][0]["strategy_id"], "day_rank_long")

    def test_missing_price_fields_are_skipped_not_guessed(self):
        data = {"day_ifo_candidates": [
            {"name": "C", "ticker": "3333.T", "side": "LONG", "score": 80},
        ]}
        snap = mr.morning_snapshot(data, datetime(2026, 9, 17, 8, 55, tzinfo=JST))
        self.assertEqual(snap["candidates"], [])


if __name__ == "__main__":
    unittest.main()
