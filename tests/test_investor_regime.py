import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.investor_regime import (
    _period_from_name,
    detect_regime, directional_return, independent_week_count, learn_sensitivity,
    parse_derivative_csv, performance_metrics, safe_z, score_with_regime,
    select_asof, subject_metrics,
)

JST = ZoneInfo("Asia/Tokyo")


class PointInTimeTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"dataset": "equity", "period_end": "2026-08-28", "retrieved_at": "2026-09-03T15:31:00+09:00", "revision": 1},
            {"dataset": "equity", "period_end": "2026-09-04", "retrieved_at": "2026-09-10T15:31:00+09:00", "revision": 1},
            {"dataset": "equity", "period_end": "2026-09-04", "retrieved_at": "2026-09-11T10:00:00+09:00", "revision": 2},
        ]

    def test_1525_never_sees_1530_release(self):
        row = select_asof(self.records, datetime(2026, 9, 10, 15, 25, tzinfo=JST), "equity")
        self.assertEqual(row["period_end"], "2026-08-28")

    def test_after_fetch_not_scheduled_time_unlocks(self):
        before_fetch = select_asof(self.records, datetime(2026, 9, 10, 15, 30, 30, tzinfo=JST), "equity")
        after_fetch = select_asof(self.records, datetime(2026, 9, 10, 15, 32, tzinfo=JST), "equity")
        self.assertEqual(before_fetch["period_end"], "2026-08-28")
        self.assertEqual(after_fetch["period_end"], "2026-09-04")

    def test_revision_is_not_backfilled(self):
        row = select_asof(self.records, datetime(2026, 9, 10, 16, 0, tzinfo=JST), "equity")
        self.assertEqual(row["revision"], 1)

    def test_holiday_delay_is_data_driven(self):
        row = select_asof(self.records, datetime(2026, 9, 9, 18, 0, tzinfo=JST), "equity")
        self.assertEqual(row["period_end"], "2026-08-28")

    def test_legacy_and_new_jpx_filenames(self):
        self.assertEqual(_period_from_name("stock_1_w_20260831_20260904.xlsx"),
                         ("2026-08-31", "2026-09-04"))
        self.assertEqual(_period_from_name("stock_val_1_260831_260904.xls"),
                         ("2026-08-31", "2026-09-04"))


class MetricTests(unittest.TestCase):
    def test_missing_and_zero_variance_do_not_become_zero_z(self):
        self.assertIsNone(safe_z(None, [1] * 52))
        self.assertIsNone(safe_z(1, [1] * 52))

    def test_flow_impulse_reversal_and_streak(self):
        weekly = []
        for i in range(52):
            net = i - 30
            weekly.append({"period_end": f"2025-{(i//4)+1:02d}-{(i%4)+1:02d}", "subjects": {"foreign": {"net": net, "gross": 100}}, "market_turnover": 1000})
        m = subject_metrics(weekly, "foreign")
        self.assertIsNotNone(m["z52"])
        self.assertGreater(m["flow_impulse"], 0)
        self.assertGreater(m["streak_weeks"], 0)

    def test_regime_requires_evidence(self):
        empty = {x: {"net": None, "z52": None, "flow_impulse": None} for x in (
            "foreign", "individual_cash", "individual_margin", "business_corporations", "trust_banks")}
        self.assertEqual(detect_regime(empty)["name"], "判定不能")

    def test_regime_foreign_reentry(self):
        rows = {x: {"net": None, "z52": None, "flow_impulse": None} for x in (
            "foreign", "individual_cash", "individual_margin", "business_corporations", "trust_banks")}
        rows["foreign"] = {"net": 100, "z52": .8, "flow_impulse": 1.5, "reversal": "売→買"}
        self.assertEqual(detect_regime(rows)["name"], "FOREIGN RE-ENTRY")

    def test_derivative_parser_requires_explicit_headers_and_identity(self):
        content = "投資部門,商品,売り取引高,買い取引高,差引\n海外投資家,日経225先物,100,140,40\n個人,日経225先物,20,30,10\n"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "f.csv"
            path.write_text(content, encoding="utf-8-sig")
            parsed = parse_derivative_csv(path, "2026-09-04")
        self.assertEqual(parsed["net"], 40)
        self.assertEqual(parsed["matched_rows"], 1)


class ScoringAndAuditTests(unittest.TestCase):
    def test_score_is_100_point_and_single_30_point_block(self):
        row = score_with_regime(100, 20, 10)
        self.assertEqual(row["score"], 100)
        self.assertEqual(row["base_70"] + row["regime_fit_20"] + row["sensitivity_10"], 100)

    def test_missing_sensitivity_is_not_fabricated(self):
        row = score_with_regime(80, 10, None)
        self.assertIsNone(row["sensitivity_10"])
        self.assertEqual(row["learning_status"], "学習不足")

    def test_short_return_and_cost(self):
        self.assertAlmostEqual(directional_return("SHORT", 100, 90), 100/90-1)
        self.assertAlmostEqual(directional_return("LONG", 100, 110, 10), .099, places=6)

    def test_independent_labels(self):
        dates = ["2026-01-05", "2026-01-06", "2026-01-12", "2026-01-19"]
        self.assertEqual(independent_week_count(dates, 5), 3)

    def test_performance_metrics_refuse_small_or_overlapping_sample(self):
        rows = [{"date": f"2026-01-{i:02d}", "return": .01} for i in range(1, 21)]
        result = performance_metrics(rows, 5, minimum_weeks=10)
        self.assertEqual(result["status"], "学習不足")
        self.assertLess(result["independent_weeks"], result["sample_count"])

    def test_sensitivity_refuses_small_sample_and_zero_variance(self):
        flow = [{"period_end": f"2026-01-{i:02d}", "subjects": {"foreign": {"z52": 1}}} for i in range(1, 27)]
        returns = [{"period_end": f"2026-01-{i:02d}", "excess_return": .01} for i in range(1, 27)]
        self.assertEqual(learn_sensitivity(flow[:10], returns[:10], "foreign")["status"], "学習不足")
        self.assertEqual(learn_sensitivity(flow, returns, "foreign")["status"], "標準偏差ゼロ")

    def test_immutable_snapshot_pattern(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "final.json"
            first = {"model_version": "v1", "score": 70}
            with target.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(first))
            with self.assertRaises(FileExistsError):
                target.open("x", encoding="utf-8")
            self.assertEqual(json.loads(target.read_text())["score"], 70)


if __name__ == "__main__":
    unittest.main()
