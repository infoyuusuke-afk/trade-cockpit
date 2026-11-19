"""OWNER 2026-11-19 「メル300万・500万は1日−1.5%に届いたらその日は新しく入らない。持ち越しの利益が入っても戻さない。100株換算の研究用メルは
止めずに大引けまで続ける。どのメルも、場中は日経の向き（寄り±0.3%と直近15分±0.15%）で、下げは空売りの手法、上げは買いの手法、どちらでも
ない時は様子見。手法Dは1銘柄1日1回。今のメルと新しいメルを両方記録して比べて」. Synthetic data only; virtual, no orders."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v10_positions_live as live  # noqa: E402

UP = [("09:00", 50000), ("09:30", 50100), ("09:45", 50250), ("10:00", 50300), ("14:00", 50400), ("14:30", 50500)]
DOWN = [("09:00", 50000), ("09:30", 49900), ("09:45", 49750), ("10:00", 49700), ("14:00", 49600), ("14:30", 49500)]
PLAN = {"methods": ["R2"], "size_pct": 50, "max_mult": 3.0, "daily_stop_pct": None, "overnight": True}


def day(rule, ticker, side, hin, hout, y100, fill=1000.0):
    return {"kind": "day", "rule": rule, "ticker": ticker, "name": ticker, "side": side, "fill": fill, "in": hin, "out": hout, "y100": y100}


class Regime(unittest.TestCase):
    def test_up_down_and_between(self):
        up = [("09:00", 50000), ("09:30", 50100), ("09:45", 50250)]
        self.assertEqual(live.mel_regime(up, "09:45"), "上げ")
        self.assertIsNone(live.mel_regime(up, "09:30"))
        dn = [("09:00", 50000), ("09:30", 49900), ("09:45", 49750)]
        self.assertEqual(live.mel_regime(dn, "09:45"), "下げ")
        flat = [("09:00", 50000), ("09:30", 50200), ("09:45", 50190)]
        self.assertIsNone(live.mel_regime(flat, "09:45"))
        self.assertIsNone(live.mel_regime([], "10:00"))

    def test_only_values_up_to_the_minute(self):
        pts = [("09:00", 50000), ("09:30", 50000), ("09:45", 50000), ("09:46", 51000)]
        self.assertIsNone(live.mel_regime(pts, "09:45"))

    def test_methods_neither_is_wait(self):
        self.assertEqual(live.mel_new_methods(UP, "09:45"), ("R1", "R4"))
        self.assertEqual(live.mel_new_methods(DOWN, "09:45"), ("R2", "R5"))
        self.assertEqual(live.mel_new_methods(UP, "09:30"), ())      # 様子見


class NewMel(unittest.TestCase):
    def test_market_picks_the_methods(self):
        tr = [day("R2", "A", -1, "09:20", "09:25", -100), day("R4", "B", 1, "09:46", "10:00", 500), day("R2", "C", -1, "09:47", "10:00", 300)]
        got = live.mel_new_day(tr, PLAN, lambda d: None, 3_000_000, 1.5, False, UP, "23:59", False)
        self.assertEqual([r["name"] for r in got["rows"]], ["B"])      # 09:20 between: 様子見; up: R4 yes, R2 no

    def test_loss_line_stays_after_an_overnight_gain(self):
        p = dict(PLAN, size_pct=100)
        tr = [{"kind": "overnight", "rule": "ON_SHORT", "ticker": "O", "name": "O", "side": -1, "fill": 1000.0, "in": "09:00", "out": "14:00",
               "y100": 10000, "decided": "2026-11-19"},
              day("R5", "A", -1, "09:46", "09:50", -2000), day("R5", "B", -1, "09:55", "10:05", 100), day("R5", "C", -1, "14:30", "14:40", 100)]
        got = live.mel_new_day(tr, p, lambda d: dict(PLAN, methods=["ON_SHORT"], size_pct=10), 3_000_000, 1.5, False, DOWN, "23:59", False)
        names = [r["name"] for r in got["rows"]]
        self.assertEqual(names, ["O", "A"])          # A's −6万 (2 %) is past −1.5 %; B (09:55) and C (14:30, after the +3万 at 14:00) not entered
        self.assertEqual(got["stopped_at"], "09:50")  # audit 1c20526 ①: the stop time is the closing time that reached the line

    def test_line_by_closing_order_even_if_it_recovers_before_the_next_entry(self):
        """audit 1c20526 ①: −1.5 % reached at 10:00, a +gain closes at 10:30; an entry at 11:00 is still blocked"""
        p = dict(PLAN, size_pct=100)
        tr = [day("R5", "A", -1, "09:46", "10:00", -2000), day("R2", "B", -1, "09:47", "10:30", 1500), day("R5", "C", -1, "11:00", "11:10", 100)]
        down = DOWN + [("11:00", 49300)]
        got = live.mel_new_day(tr, p, lambda d: None, 3_000_000, 1.5, False, sorted(down), "23:59", False)
        self.assertEqual([r["name"] for r in got["rows"]], ["A", "B"])
        self.assertEqual(got["stopped_at"], "10:00")

    def test_no_overnight_from_a_stopped_day(self):
        """audit 1c20526 ②: the 15:25 hold decided on a day the account stopped is not entered the next day"""
        tr = [{"kind": "overnight", "rule": "ON_SHORT", "ticker": "O", "name": "O", "side": -1, "fill": 1000.0, "in": "09:00", "out": "14:00",
               "y100": 1000, "decided": "2026-11-20"}]
        dp = lambda d: dict(PLAN, methods=["ON_SHORT"], size_pct=10)
        self.assertEqual(live.mel_new_day(tr, PLAN, dp, 3_000_000, 1.5, False, DOWN, "23:59", False, frozenset({"2026-11-20"}))["n"], 0)
        self.assertEqual(live.mel_new_day(tr, PLAN, dp, 3_000_000, 1.5, False, DOWN, "23:59", False, frozenset())["n"], 1)
        self.assertEqual(live.mel_new_day(tr, None, dp, 0.0, None, True, DOWN, "23:59", False, frozenset({"2026-11-20"}))["n"], 1)  # 100株: no stop

    def test_rss_error_is_not_a_price(self):
        """audit 1c20526 ③: an Excel error code or a non-number from RSS is recorded as RSS_ERROR with no price"""
        src = (ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('$fiStatus = "RSS_ERROR"', src)
        self.assertIn("-le -2146826200", src)
        self.assertIn("[double]::TryParse([string]$fiV0", src)
        self.assertIn('$ok = ($fiStatus -eq "OK" -or ($isFx -and $fiStatus -like "STALE_*"))', src)   # RSS_ERROR rows write no price

    def test_hundred_never_stops_and_d_once_per_stock(self):
        tr = [day("R5", "A", -1, "09:46", "09:50", -20000), day("R5", "A", -1, "10:00", "10:05", 100), day("R2", "B", -1, "14:30", "14:40", 100)]
        got = live.mel_new_day(tr, None, lambda d: None, 0.0, None, True, DOWN, "23:59", False)
        self.assertEqual([(r["name"], r["shares"]) for r in got["rows"]], [("A", 100), ("B", 100)])   # A's 2nd 手法D not taken
        self.assertIsNone(got["stopped_at"])

    def test_no_plan_no_day_trade_for_money_accounts(self):
        tr = [day("R4", "B", 1, "09:46", "10:00", 500)]
        self.assertEqual(live.mel_new_day(tr, None, lambda d: None, 3_000_000, 1.5, False, UP, "23:59", False)["n"], 0)
        self.assertEqual(live.mel_new_day(tr, None, lambda d: None, 0.0, None, True, UP, "23:59", False)["n"], 1)

    def test_accounts_and_the_current_mel_unchanged(self):
        # OWNER 2026-11-19 「５００万メルは削除して」
        self.assertEqual([a[0] for a in live.MEL_NEW_ACCOUNTS], ["300万", "100株"])
        self.assertEqual([a[2] for a in live.MEL_NEW_ACCOUNTS], [1.5, None])
        src = (ROOT / "scripts" / "v10_positions_live.py").read_text(encoding="utf-8")
        a = src.index("def mel_today(")
        self.assertIn('if not plan or t.get("rule") not in plan["methods"]:', src[a:a + 3000])   # the current メル keeps its rules


if __name__ == "__main__":
    unittest.main()
