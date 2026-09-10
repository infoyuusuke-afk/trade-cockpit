import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from scripts.investor_regime import (
    _equity_period, _equity_subjects, _period_from_name,
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
    def test_equity_workbook_uses_covered_range_and_current_columns(self):
        frame = pd.DataFrame([[None] * 11 for _ in range(78)])
        frame.iat[3, 0] = "2026年9月第1週 2026/9 week1  ( 8/31 - 9/4 )"
        frame.iat[8, 1] = "100,845,017,660"
        blocks = {
            12: ("自己計", 5_324_742_290, 5_242_555_463),
            29: ("海外投資家", 29_610_539_594, 30_299_882_474),
            37: ("投資信託", 1_079_043_527, 775_211_875),
            40: ("事業法人", 365_696_869, 643_687_123),
            51: ("生保・損保", 69_086_002, 20_736_097),
            57: ("信託銀行", 1_294_765_354, 847_843_066),
        }
        for i, (label, sell, buy) in blocks.items():
            frame.iat[i, 0] = label; frame.iat[i, 8] = sell
            frame.iat[i + 1, 8] = buy
        frame.iat[67, 0] = "個人現金\nIndividual Cash"
        frame.iat[67, 2] = 2_534_211_897; frame.iat[67, 4] = 2_447_219_131
        frame.iat[68, 0] = "個人信用\nIndividual Margin"
        frame.iat[68, 2] = 9_470_088_390; frame.iat[68, 4] = 9_555_213_558
        self.assertEqual(_equity_period(frame), ("2026-08-31", "2026-09-04"))
        subjects, turnover = _equity_subjects(frame)
        self.assertEqual(subjects["foreign"]["net"], 689_342_880)
        self.assertEqual(subjects["individual_margin"]["net"], 85_125_168)
        self.assertEqual(subjects["life_insurance"]["source_label"], "生保・損保（公式合算）")
        self.assertNotIn("non_life_insurance", subjects)
        self.assertEqual(turnover, 100_845_017_660)

    def test_missing_and_zero_variance_do_not_become_zero_z(self):
        self.assertIsNone(safe_z(None, [1] * 52))
        self.assertIsNone(safe_z(1, [1] * 52))

    def test_flow_impulse_reversal_and_streak(self):
        weekly = []
        for i in range(53):
            net = i - 30
            weekly.append({"period_end": f"2025-{(i//4)+1:02d}-{(i%4)+1:02d}", "subjects": {"foreign": {"net": net, "gross": 100}}, "market_turnover": 1000})
        m = subject_metrics(weekly, "foreign")
        self.assertIsNotNone(m["z52"])
        self.assertIsNotNone(m["flow_impulse"])
        self.assertGreater(m["streak_weeks"], 0)

    def test_partial_history_is_not_mislabeled_as_13_or_52_weeks(self):
        weekly = [
            {"period_end": f"2026-08-{i:02d}",
             "subjects": {"foreign": {"net": i, "gross": 100}},
             "market_turnover": 1000}
            for i in range(1, 6)
        ]
        m = subject_metrics(weekly, "foreign")
        self.assertEqual(m["cumulative_4w"], 2 + 3 + 4 + 5)
        self.assertIsNone(m["cumulative_13w"])
        self.assertIsNone(m["cumulative_52w"])
        self.assertIsNone(m["z52"])

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

    def test_derivative_current_code_format_uses_value_rows_only(self):
        content = ("帳票種別 Product type,サイクル区分 Cycle,\"年月週 Year, Month, Week\","
                   "報告年月日（自）Period covered - from,報告年月日（至）Period covered - to,"
                   "投資部門コード Type of Investor,数量金額区分 Volume/Value,売 Sales,"
                   "売-差引 Balance,買 Purchases,買-差引 Balance,合計 Total\n"
                   "301,1,2026091,20260831,20260904,60,1,100,0,140,40,240\n"
                   "301,1,2026091,20260831,20260904,60,2,100000,0,140000,40000,240000\n"
                   "313,1,2026091,20260831,20260904,60,2,200000,50000,150000,0,350000\n"
                   "314,1,2026091,20260831,20260904,60,2,1,0,999,998,1000\n"
                   "301,1,2026091,20260831,20260904,51,2,1,0,999,998,1000\n")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "f.csv"
            path.write_text(content, encoding="utf-8-sig")
            parsed = parse_derivative_csv(path, "bad-fallback")
        self.assertEqual(parsed["period_end"], "2026-09-04")
        self.assertEqual(parsed["net"], -10_000)
        self.assertEqual(parsed["matched_rows"], 2)
        self.assertEqual(parsed["basis"], "trading_value_yen")


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
