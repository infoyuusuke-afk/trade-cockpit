import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "pd",
    Path(__file__).parents[1] / "scripts" / "performance_dashboard.py",
)
pd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pd)


class PerformanceDashboardTests(unittest.TestCase):
    def test_legacy_row_without_identity_stays_unclassified(self):
        dashboard = pd.build_dashboard([
            {"date": "2026-09-01", "result": "大引け決済", "pnl_yen": 1000}
        ])
        self.assertEqual(dashboard["classified_record_count"], 0)
        self.assertEqual(dashboard["unclassified_record_count"], 1)
        self.assertEqual(dashboard["strategies"], [])

    def test_known_strategy_maps_to_realtime_but_mode_is_unknown_not_shadow_guess(self):
        dashboard = pd.build_dashboard([
            {
                "date": "2026-09-01",
                "strategy_id": "day_rank_long",
                "result": "IFO利確1",
                "exit_reason": "TARGET1",
                "pnl_yen": 1000,
                "r": 1.0,
            }
        ])
        self.assertEqual(len(dashboard["strategies"]), 1)
        lane = dashboard["strategies"][0]
        self.assertEqual(lane["tab"], "ms2-live")
        self.assertEqual(lane["mode"], "unknown")
        self.assertEqual(dashboard["unknown_mode_record_count"], 1)

    def test_open_mark_is_not_realized(self):
        lane = pd.compute_lane(
            "ms2-live",
            "shadow",
            [
                {
                    "date": "2026-09-01",
                    "exit_reason": "OPEN_MARK",
                    "result": "時点評価・未決済",
                    "pnl_yen": 5000,
                    "r": 0.5,
                }
            ],
        )
        self.assertEqual(lane["sample_count"], 0)
        self.assertEqual(lane["unresolved_count"], 1)
        self.assertIsNone(lane["pnl_yen"])
        self.assertIsNone(lane["win_rate"])

    def test_not_triggered_is_not_a_loss(self):
        lane = pd.compute_lane(
            "event-hot",
            "shadow",
            [
                {
                    "date": "2026-09-01",
                    "exit_reason": "NOT_TRIGGERED",
                    "result": "未発動（見送り）",
                    "pnl_yen": None,
                }
            ],
        )
        self.assertEqual(lane["sample_count"], 0)
        self.assertEqual(lane["not_triggered_count"], 1)
        self.assertEqual(lane["losses"], 0)

    def test_profit_factor_without_losses_is_explicit_not_magic_number(self):
        lane = pd.compute_lane(
            "scalp",
            "shadow",
            [
                {"date": "2026-09-01", "exit_reason": "TARGET1", "pnl_yen": 1000},
                {"date": "2026-09-02", "exit_reason": "TARGET1", "pnl_yen": 2000},
            ],
        )
        self.assertIsNone(lane["pf"])
        self.assertEqual(lane["pf_status"], "NO_LOSSES")

    def test_mode_separation(self):
        rows = [
            {
                "date": "2026-09-01",
                "cockpit_tab": "scalp",
                "execution_mode": "shadow",
                "exit_reason": "TARGET1",
                "pnl_yen": 1000,
            },
            {
                "date": "2026-09-01",
                "cockpit_tab": "scalp",
                "execution_mode": "backtest",
                "exit_reason": "STOP",
                "pnl_yen": -500,
            },
        ]
        dashboard = pd.build_dashboard(rows)
        lanes = {(x["tab"], x["mode"]): x for x in dashboard["strategies"]}
        self.assertEqual(lanes[("scalp", "shadow")]["pnl_yen"], 1000)
        self.assertEqual(lanes[("scalp", "backtest")]["pnl_yen"], -500)
        self.assertEqual(len(lanes), 2)

    def test_max_drawdown_uses_realized_equity_curve(self):
        lane = pd.compute_lane(
            "scalp",
            "shadow",
            [
                {"date": "2026-09-01", "exit_reason": "TARGET1", "pnl_yen": 1000},
                {"date": "2026-09-02", "exit_reason": "STOP", "pnl_yen": -400},
                {"date": "2026-09-03", "exit_reason": "STOP", "pnl_yen": -900},
                {"date": "2026-09-04", "exit_reason": "TARGET1", "pnl_yen": 300},
            ],
        )
        self.assertEqual(lane["max_drawdown_yen"], -1300)

    def test_daily_and_cumulative_series(self):
        lane = pd.compute_lane(
            "scalp",
            "shadow",
            [
                {"date": "2026-09-01", "exit_reason": "TARGET1", "pnl_yen": 1000},
                {"date": "2026-09-01", "exit_reason": "STOP", "pnl_yen": -200},
                {"date": "2026-09-02", "exit_reason": "TARGET1", "pnl_yen": 500},
            ],
        )
        self.assertEqual(
            lane["daily_series"],
            [
                {"date": "2026-09-01", "pnl_yen": 800.0, "trades": 2, "cum_pnl_yen": 800.0},
                {"date": "2026-09-02", "pnl_yen": 500.0, "trades": 1, "cum_pnl_yen": 1300.0},
            ],
        )

    def test_recent_trades_is_capped_at_twenty(self):
        rows = [
            {
                "date": f"2026-09-{i:02d}",
                "exit_reason": "TARGET1",
                "pnl_yen": i,
            }
            for i in range(1, 26)
        ]
        lane = pd.compute_lane("scalp", "shadow", rows)
        self.assertEqual(len(lane["recent_trades"]), 20)
        self.assertEqual(lane["recent_trades"][-1]["date"], "2026-09-25")

    def test_missing_tabs_are_unknown_not_zero(self):
        dashboard = pd.build_dashboard([])
        missing = {x["tab"]: x for x in dashboard["missing_strategy_tabs"]}
        self.assertEqual(missing["scalp"]["source_status"], "unknown")
        self.assertNotIn("sample_count", missing["scalp"])


if __name__ == "__main__":
    unittest.main()
