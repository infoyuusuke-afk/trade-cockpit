from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8-sig")


class V10ControlDashboardContractTests(unittest.TestCase):
    def test_control_loads_normalized_performance_artifact(self):
        text = read("trade_control.js")
        self.assertIn('fetch("performance_by_strategy.json?t="+Date.now()', text)
        self.assertIn('id="strategy-performance-dashboard"', text)
        self.assertIn("戦略別成績ダッシュボード", text)

    def test_control_has_visual_performance_components(self):
        text = read("trade_control.js")
        for needle in (
            "performanceSparkline",
            "cc-performance-rank",
            "cc-performance-track",
            "cc-performance-cards",
            "累積損益推移",
            "最大DD",
        ):
            self.assertIn(needle, text)

    def test_open_mark_is_excluded_from_realized_stats(self):
        text = read("trade_control.js")
        self.assertIn('["OPEN_MARK","NOT_TRIGGERED","AMBIGUOUS_EXCLUDED","UNKNOWN",""]', text)
        self.assertIn("const isRealized=x=>", text)
        self.assertIn("const done=rows.filter(isRealized)", text)

    def test_real_shadow_backtest_modes_are_not_silently_guessed(self):
        text = read("trade_control.js")
        self.assertIn('return ["real","shadow","backtest"].includes(raw)?raw:"unknown"', text)
        self.assertIn("REAL/SHADOW/BACKTESTは混合しません", text)
        self.assertIn("unknown_mode_record_count", text)

    def test_profit_factor_has_no_magic_99_sentinel_in_control(self):
        text = read("trade_control.js")
        self.assertNotIn("gains>0?99", text)
        self.assertIn('"NO_LOSSES"', text)

    def test_client_fallback_remains_traceable_and_unknown_safe(self):
        text = read("trade_control.js")
        self.assertIn("buildClientPerformance", text)
        self.assertIn('source_status:"client_fallback"', text)
        self.assertIn("unclassified_record_count", text)
        self.assertIn("missing_strategy_tabs", text)


if __name__ == "__main__":
    unittest.main()
