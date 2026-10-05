import copy
import sys
import unittest
from pathlib import Path

from scripts import journal_projection as jp


def _trade(**overrides):
    row = {
        "trade_id": "285A.T|LONG|1",
        "symbol": "285A.T",
        "side": "LONG",
        "source_stage": "LIVE_SHADOW",
        "decision_at": "2026-10-05T09:16:05+09:00",
        "exit_fill_at": "2026-10-05T09:20:05+09:00",
        "available_at": "09:16:00",
        "gross_pnl": 40,
        "commission": "FEE_UNKNOWN",
        "other_cost": "FEE_UNKNOWN",
        "net_pnl": "FEE_UNKNOWN",
        "fee_basis": "UNCONFIRMED",
        "quantity": None,
        "real_submit_allowed": False,
    }
    row.update(overrides)
    return row


class ShadowTradeJournalTests(unittest.TestCase):
    def test_unknown_fee_stays_unpriced_and_source_is_unchanged(self):
        trade = _trade()
        before = copy.deepcopy(trade)
        rows = jp.shadow_trade_journal_rows([trade])
        self.assertEqual(trade, before)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(len(row["event_id"]), 64)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in row["event_id"]))
        self.assertIsNone(row["result"])
        self.assertNotIn("0", row["summary"])
        self.assertNotIn("40", row["summary"])
        self.assertIn("commission=FEE_UNKNOWN", row["lesson"])
        self.assertIn("net_pnl_not_recorded", row["lesson"])
        self.assertIn("real_submit_allowed=false", row["summary"])
        self.assertNotIn("real_submit_allowed", row)
        self.assertEqual(set(row), {
            "event_id", "timestamp", "symbol", "category", "event_type",
            "summary", "decision", "result", "lesson",
        })

    def test_synthetic_cannot_count_as_live_experience(self):
        trade = _trade(
            source_stage="SYNTHETIC/REPLAY",
            commission=1.0,
            other_cost=0.25,
            net_pnl=38.75,
            fee_basis="SYNTHETIC_FIXTURE_NOT_A_BROKER_TARIFF",
        )
        rows = jp.shadow_trade_journal_rows([trade])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["result"])
        self.assertIn("counts_as_live_experience=false", rows[0]["lesson"])
        self.assertIn("SYNTHETIC/REPLAY", rows[0]["summary"])
        self.assertNotIn("38.75", rows[0]["summary"] + (rows[0]["result"] or ""))

    def test_assumed_zero_is_not_written_as_a_result(self):
        trade = _trade(commission=0, other_cost=0, net_pnl=0, fee_basis="ASSUMED_ZERO")
        rows = jp.shadow_trade_journal_rows([trade])
        self.assertIsNone(rows[0]["result"])
        self.assertIn("fee_basis_unconfirmed", rows[0]["lesson"])

    def test_partial_clock_real_submit_and_duplicate_are_dropped(self):
        partial = _trade(exit_fill_at="09:20:00", decision_at="09:16:00")
        real = _trade(trade_id="285A.T|LONG|2", real_submit_allowed=True)
        missing = _trade(trade_id="285A.T|LONG|3", real_submit_allowed=None)
        first = _trade()
        rows = jp.shadow_trade_journal_rows([partial, real, missing, first, copy.deepcopy(first)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "285A.T")

    def test_confirmed_basis_can_record_a_numeric_net_without_touching_the_empty_set(self):
        sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
        import shadow_trade_ledger as trade_ledger

        self.assertEqual(set(trade_ledger.CONFIRMED_LIVE_FEE_BASES), set())
        original = trade_ledger.CONFIRMED_LIVE_FEE_BASES
        trade_ledger.CONFIRMED_LIVE_FEE_BASES = frozenset({"TEST_ONLY_NOT_A_TARIFF"})
        try:
            trade = _trade(commission=1.0, other_cost=0.5, net_pnl=38.5, fee_basis="TEST_ONLY_NOT_A_TARIFF")
            rows = jp.shadow_trade_journal_rows([trade])
            self.assertEqual(rows[0]["result"], "38.5")
            self.assertIsNone(rows[0]["lesson"])
        finally:
            trade_ledger.CONFIRMED_LIVE_FEE_BASES = original
        self.assertEqual(set(trade_ledger.CONFIRMED_LIVE_FEE_BASES), set())

    def test_projection_does_not_read_private_holdings(self):
        text = Path(jp.__file__).read_text(encoding="utf-8")
        self.assertNotIn("private_ledger", text)
        self.assertNotIn("data/private", text)
        self.assertNotIn("submit_shadow_order", text)
