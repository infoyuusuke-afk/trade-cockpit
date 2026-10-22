"""OWNER 2026-10-22 R2: 地合い弱い = at most 40 % of the issues above their reference price
(基準値), not the Collector's above-VWAP breadth. Synthetic data only; no orders."""
from datetime import datetime, timedelta, timezone
import unittest
from pathlib import Path

from scripts import v10_brain_core as brain
from scripts import v10_signal_ev_table as ev

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 22, 0, 30, tzinfo=timezone.utc)  # 09:30 JST
SHORT = "空売りサイン"


def context(up, down, at="09:10:00"):
    ticks = {}
    for i in range(up):
        ticks["U%02d.T" % i] = [(at, 0, 101.0)]
    for i in range(down):
        ticks["D%02d.T" % i] = [(at, 0, 99.0)]
    reference = {t: 100.0 for t in ticks}
    return ev.day_context(None, ticks, reference)


def signal(at="09:30:00", market="地合い中立"):
    return {"captured_at": "2026-10-22 " + at, "ticker": "X.T", "signal": SHORT, "strategy": "OR15戻り",
            "entry": "1000", "stop": "1010", "target1": "990", "market_state": market}


class RuleShadowBreadth(unittest.TestCase):
    def test_rule_has_no_vwap_market_condition(self):
        r2 = ev.RULES["R2"]
        self.assertIsNone(r2["market"])
        self.assertEqual(r2["advance_max_pct"], 40.0)

    def test_share_above_reference_at_the_signal_time(self):
        self.assertEqual(ev.advance_pct_at(context(8, 12), "09:30:00"), 40.0)
        self.assertIsNone(ev.advance_pct_at(context(8, 11), "09:30:00"))      # 19 issues: too few
        self.assertIsNone(ev.advance_pct_at(context(8, 12), "09:05:00"))      # no trade yet: no look-ahead
        flat = context(0, 20)
        flat["series"]["E.T"] = (["09:10:00"], [100.0])
        flat["ref"]["E.T"] = 100.0
        self.assertEqual(ev.advance_pct_at(flat, "09:30:00"), 0.0)            # unchanged is not up

    def test_r2_matches_only_when_at_most_40_percent_are_up(self):
        r2 = ev.RULES["R2"]
        self.assertTrue(ev.rule_matches(r2, signal(market="地合い中立"), context(8, 12)))   # VWAP state ignored
        self.assertFalse(ev.rule_matches(r2, signal(market="地合い弱い"), context(9, 11)))  # 45 % up
        self.assertFalse(ev.rule_matches(r2, signal(), None))                              # unknown: no match


def row(ticker, price, ref, fresh=True, sig=None):
    out = {"ticker": ticker, "name": ticker, "price": price, "reference_price": ref, "aggregate_row_fresh": fresh}
    if sig:
        out.update(signal=sig, strategy="OR15戻り", signal_bar_time="2026-10-22 09:29", entry_price=1000,
                   stop_price=1010, target1=990, credit_ratio=3.0, market_state="地合い中立")
    return out


class BrainBreadth(unittest.TestCase):
    SHADOW = {"schema_version": ev.RULES_SCHEMA, "real_submit_allowed": False, "forward_from": "2026-10-22",
              "rules": ev.RULES, "forward": {}}

    def board(self, up, down):
        rows = [row("U%02d.T" % i, 101, 100) for i in range(up)] + [row("D%02d.T" % i, 99, 100) for i in range(down)]
        rows.append(row("X.T", 999, 1000, sig=SHORT))
        return {"updated_at": "2026-10-22 09:29:55", "valid": 100, "stale": False, "all_targets": rows}

    def test_advance_pct_counts_fresh_rows_with_both_prices(self):
        rows = [row("A", 101, 100), row("B", 99, 100), row("C", 101, 100, fresh=False), row("D", None, 100)]
        self.assertIsNone(brain.advance_pct(rows))
        rows = [row("U%d" % i, 101, 100) for i in range(5)] + [row("D%d" % i, 99, 100) for i in range(15)]
        self.assertEqual(brain.advance_pct(rows), 25.0)

    def test_r2_used_only_on_a_weak_board(self):
        weak = brain.pick(self.board(7, 13), ev_table=None, rule_shadow=self.SHADOW, now=NOW)
        self.assertEqual(weak["advance_pct"], 33.3)   # 7 of 21: X.T (999 < 1000) is the 21st row, down
        self.assertEqual([p["rule"] for p in weak["picks"]], ["R2"])
        strong = brain.pick(self.board(12, 8), ev_table=None, rule_shadow=self.SHADOW, now=NOW)
        self.assertEqual(strong["picks"], [])
        self.assertFalse(strong["real_submit_allowed"])

    def test_screen_uses_the_same_rule(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("if(r.advance_max_pct!=null&&!(evAdvancePct!=null&&evAdvancePct<=r.advance_max_pct))continue;", html)
        self.assertIn("b.length>=20?", html)


if __name__ == "__main__":
    unittest.main()
