import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('rr', Path(__file__).parents[1] / 'scripts/reliability_report.py')
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)


def trade(r, triggered=True, **extra):
    return {"triggered": triggered, "r": r, **extra}


class SummarizeTests(unittest.TestCase):
    def test_counts_only_triggered_numeric_r_as_resolved(self):
        records = [trade(1.0), trade(None, triggered=True), trade(1.0, triggered=False)]
        s = rr.summarize(records)
        self.assertEqual(s["total_recorded"], 3)
        self.assertEqual(s["resolved_n"], 1)

    def test_win_rate_and_pf(self):
        records = [trade(1.0), trade(1.0), trade(-1.0)]
        s = rr.summarize(records)
        self.assertAlmostEqual(s["win_rate_pct"], 66.7, places=1)
        self.assertEqual(s["profit_factor"], 2.0)

    def test_below_min_n_is_not_reliable(self):
        s = rr.summarize([trade(1.0)])
        self.assertEqual(s["status"], "試運転・検証中（サンプル不足）")


class WilsonIntervalTests(unittest.TestCase):
    def test_zero_n_returns_zero_interval(self):
        self.assertEqual(rr.wilson_interval(0, 0), (0.0, 0.0))

    def test_interval_contains_point_estimate(self):
        lower, upper = rr.wilson_interval(15, 30)
        self.assertLess(lower, 50.0)
        self.assertGreater(upper, 50.0)


class ByStrategyGroupingTests(unittest.TestCase):
    """The grouping logic added for Issue #18 (C-045-GPT priority 1) lives inline in
    main(), so this exercises the same filtering rules main() applies rather than
    calling main() itself (which touches real files)."""

    def test_untagged_legacy_records_are_not_dropped(self):
        history = [
            trade(1.0, strategy_id="day_ifo_long"),
            trade(-1.0),  # no strategy_id -- pre-schema legacy record
        ]
        strategy_ids = sorted({r.get("strategy_id") for r in history if r.get("strategy_id")})
        by_strategy = {sid: rr.summarize([r for r in history if r.get("strategy_id") == sid]) for sid in strategy_ids}
        untagged = [r for r in history if not r.get("strategy_id")]
        if untagged:
            by_strategy["UNTAGGED_LEGACY"] = rr.summarize(untagged)
        self.assertEqual(set(by_strategy), {"day_ifo_long", "UNTAGGED_LEGACY"})
        self.assertEqual(by_strategy["day_ifo_long"]["resolved_n"], 1)
        self.assertEqual(by_strategy["UNTAGGED_LEGACY"]["resolved_n"], 1)

    def test_no_untagged_bucket_when_all_records_tagged(self):
        history = [trade(1.0, strategy_id="day_ifo_long")]
        untagged = [r for r in history if not r.get("strategy_id")]
        self.assertEqual(untagged, [])


if __name__ == "__main__":
    unittest.main()
