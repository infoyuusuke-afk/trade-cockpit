import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("research_cost_model", ROOT / "scripts" / "research_cost_model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cost = _load()


class ResearchCostModelTests(unittest.TestCase):
    def test_official_page_is_recorded_and_not_applied(self):
        schedule = cost.fee_schedule()
        self.assertEqual(schedule["evidence_url"], "https://www.rakuten-sec.co.jp/web/domestic/stock/commission.html")
        self.assertEqual(schedule["fetched_at"], "2026-10-05")
        self.assertIsNone(schedule["tariff_version"])
        self.assertIsNone(schedule["effective_from"])
        self.assertIsNone(schedule["account_course"])
        self.assertIsNone(schedule["commission_yen"])
        self.assertEqual(schedule["commission_status"], "FEE_UNKNOWN")
        self.assertFalse(schedule["applied_to_live_sample"])
        self.assertFalse(schedule["applied_to_shadow_net"])
        self.assertEqual(cost.shadow_commission(), "FEE_UNKNOWN")
        self.assertEqual([item["course"] for item in schedule["candidate_courses"]], ["ゼロコース", "超割コース", "いちにち定額コース"])
        self.assertFalse(schedule["real_submit_allowed"])

    def test_spread_is_observed_and_slippage_stays_separate(self):
        self.assertIsNone(cost.observe_spread(None, 120))
        self.assertIsNone(cost.observe_spread(120, 100))
        self.assertEqual(cost.observe_spread(100, 100), 0.0)
        parts = cost.cost_components(
            entry_bid=19110,
            entry_ask=19130,
            exit_bid=19170,
            exit_ask=19190,
            entry_slippage=10,
            exit_slippage=10,
        )
        self.assertEqual(parts["entry_spread"], 20.0)
        self.assertEqual(parts["exit_spread"], 20.0)
        self.assertEqual(parts["entry_slippage"], 10.0)
        self.assertEqual(parts["commission"], "FEE_UNKNOWN")
        self.assertEqual(parts["exchange_fee"], "FEE_UNKNOWN")
        self.assertEqual(parts["other_cost"], "FEE_UNKNOWN")
        self.assertFalse(parts["applied_to_shadow_net"])
        missing = cost.cost_components(
            entry_bid=None,
            entry_ask=None,
            exit_bid=None,
            exit_ask=None,
            entry_slippage=None,
            exit_slippage=None,
        )
        self.assertEqual(missing["spread_status"], "UNOBSERVED")
        self.assertIsNone(missing["entry_spread"])

    def test_module_does_not_submit(self):
        text = (ROOT / "scripts" / "research_cost_model.py").read_text(encoding="utf-8")
        self.assertNotIn("submit_shadow_order", text)
        self.assertNotIn("shadow_execution", text)
        self.assertNotIn("commission_yen\"] = 0", text)
        self.assertNotIn("commission_yen = 0", text)
