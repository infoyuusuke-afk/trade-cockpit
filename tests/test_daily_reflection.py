import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('dr', Path(__file__).parents[1] / 'scripts/daily_reflection.py')
dr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dr)


def leg(**overrides):
    entry = {
        "trade_id": "T-1", "ticker": "7013", "name": "IHI", "side": "BUY",
        "price": 2772.5, "quantity": 100, "fee": 55,
        "executed_at": "2026-09-15 09:05:00",
        "horizon": "day", "strategy_version": "v1", "source": "manual",
        "position_id": "P1", "order_id": None, "execution_id": None,
        "decision_snapshot_id": None, "regime": None,
        "entry_reason": "ブレイクアウト", "exit_reason": None,
        "rule_violation": [], "reconciliation_status": "未照合",
    }
    entry.update(overrides)
    return entry


class PairPositionsTests(unittest.TestCase):
    def test_closed_position_computes_realized_pnl(self):
        entries = [
            leg(trade_id="T-1", side="BUY", price=2772.5, quantity=100, fee=55,
                executed_at="2026-09-15 09:05:00"),
            leg(trade_id="T-2", side="SELL", price=2800, quantity=100, fee=55,
                exit_reason="利確", executed_at="2026-09-15 10:30:00"),
        ]
        positions = dr.pair_positions(entries)
        self.assertEqual(len(positions), 1)
        p = positions[0]
        self.assertEqual(p["status"], "決済済み")
        self.assertEqual(p["realized_pnl_yen"], 2640)

    def test_open_position_has_no_realized_pnl(self):
        entries = [leg(trade_id="T-1", side="BUY", quantity=100)]
        positions = dr.pair_positions(entries)
        self.assertEqual(positions[0]["status"], "保有中")
        self.assertIsNone(positions[0]["realized_pnl_yen"])

    def test_entry_without_position_id_is_unmatched(self):
        entries = [leg(trade_id="T-1", position_id=None)]
        positions = dr.pair_positions(entries)
        self.assertEqual(positions[0]["status"], "ペア不可（position_id未記入）")
        self.assertIsNone(positions[0]["realized_pnl_yen"])


class BuildReflectionTests(unittest.TestCase):
    def test_no_entries_returns_no_record_status(self):
        reflection = dr.build_reflection("2026-09-15", [], [])
        self.assertEqual(reflection["status"], "実績未取得")
        self.assertIsNone(reflection["pnl_total_yen"])

    def test_rule_violation_drives_improvement_point(self):
        entries = [leg(rule_violation=["損切りルール逸脱"])]
        reflection = dr.build_reflection("2026-09-15", entries, entries)
        self.assertEqual(len(reflection["discipline_notes"]), 1)
        self.assertIn("損切りルール逸脱", reflection["improvement_point"])

    def test_missing_reason_flagged_when_no_violation(self):
        entries = [leg(side="SELL", exit_reason=None, entry_reason=None)]
        reflection = dr.build_reflection("2026-09-15", entries, entries)
        self.assertEqual(reflection["missing_reason_count"], 1)
        self.assertIn("entry_reason/exit_reason", reflection["improvement_point"])

    def test_clean_day_has_generic_improvement_point(self):
        entries = [leg(side="BUY", entry_reason="ブレイクアウト", rule_violation=[])]
        reflection = dr.build_reflection("2026-09-15", entries, entries)
        self.assertEqual(reflection["discipline_notes"], [])
        self.assertEqual(reflection["missing_reason_count"], 0)
        self.assertIn("記録・記入漏れなし", reflection["improvement_point"])

    def test_pnl_total_sums_only_positions_closed_that_day(self):
        buy = leg(trade_id="T-1", side="BUY", price=2772.5, quantity=100, fee=55,
                   executed_at="2026-09-14 09:05:00")
        sell = leg(trade_id="T-2", side="SELL", price=2800, quantity=100, fee=55,
                    executed_at="2026-09-15 10:30:00")
        all_entries = [buy, sell]
        reflection = dr.build_reflection("2026-09-15", [sell], all_entries)
        self.assertEqual(reflection["pnl_total_yen"], 2640)

    def test_same_input_gives_same_output(self):
        entries = [leg(rule_violation=["逸脱A"])]
        r1 = dr.build_reflection("2026-09-15", entries, entries)
        r2 = dr.build_reflection("2026-09-15", entries, entries)
        self.assertEqual(r1["improvement_point"], r2["improvement_point"])
        self.assertEqual(r1["discipline_notes"], r2["discipline_notes"])


class RenderTextTests(unittest.TestCase):
    def test_no_record_status_renders_without_crashing(self):
        reflection = dr.build_reflection("2026-09-15", [], [])
        text = dr.render_text(reflection)
        self.assertIn("実績未取得", text)

    def test_record_status_includes_pnl_and_improvement(self):
        entries = [leg(rule_violation=["逸脱A"])]
        reflection = dr.build_reflection("2026-09-15", entries, entries)
        text = dr.render_text(reflection)
        self.assertIn("翌日への改善点", text)
        self.assertIn("逸脱A", text)


if __name__ == "__main__":
    unittest.main()
