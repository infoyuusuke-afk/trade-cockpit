"""OWNER 2026-11-10 「１４：０　文字切れ　ー６７９３５５なのか　意味がよくわからない」: the overnight line stayed at 0 all day and fell
at 14:00, because ticks.csv began with yesterday's 15:24:59 trades (captured at 09:00 during the MS2 stop) and price_at() stops at the
first later time. Synthetic data only; no MS2, no orders."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v10_positions_live as live  # noqa: E402

HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class TickFromToday(unittest.TestCase):
    def test_rule(self):
        f = live._tick_from_today
        self.assertFalse(f("15:24:59", "2026-11-10 09:00:04.557"))   # yesterday's close seen at 09:00
        self.assertFalse(f("07:59:59", "2026-11-10 09:10:00"))
        self.assertTrue(f("09:31:28", "2026-11-10 09:31:30.100"))
        self.assertTrue(f("09:33:30", "2026-11-10 09:31:30"))         # two minutes of clock slack
        self.assertFalse(f("09:33:31", "2026-11-10 09:31:30"))
        self.assertTrue(f("11:29:58", "2026-11-10 12:10:00"))         # lunch: the morning's last trade is today's
        self.assertTrue(f("15:24:59", ""))                            # no capture time: kept as before
        self.assertTrue(f("15:24:59", "2026-11-10 12:3x:45"))         # a broken capture time never raises

    def test_price_found_after_a_stale_start(self):
        rows = ['"captured_at","ticker","name","exchange_time","price"',
                '"2026-11-10 09:00:04.557","4062.T","x","15:24:59","5903"',
                '"2026-11-10 09:31:30.000","4062.T","x","09:31:28","6203"',
                '"2026-11-10 13:59:50.000","4062.T","x","13:59:49","6332"']
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ticks.csv"
            p.write_text("\n".join(rows) + "\n", encoding="utf-8")
            st = {}
            live._read_new_ticks(p, st, {"4062.T"})
        tk = st["ticks"]["4062.T"]
        self.assertEqual([x[0] for x in tk], ["09:31:28", "13:59:49"])
        self.assertIsNone(live.price_at(tk, "09:00"))
        self.assertEqual(live.price_at(tk, "10:00"), 6203.0)
        self.assertEqual(live.price_at(tk, "14:00"), 6332.0)


class OvernightChartText(unittest.TestCase):
    def test_last_hour_label_not_cut(self):
        # audit ace1aed: only the label at the right edge is anchored at its end (15:00 on the 15:30 chart stays centred)
        self.assertIn("""text-anchor="'+(xs(hm)>W-R-20?"end":"middle")+'">'""", HTML)

    def test_line_green_above_zero_red_below(self):
        # OWNER 2026-11-11 「ーの時は赤、プラスになったら緑ラインにして」
        self.assertIn('<stop offset="0" stop-color="#35e2ae"/>', HTML)
        self.assertIn("stroke=\"url(#'+id+')\" stroke-width=\"2.5\"", HTML)
        self.assertIn("確定＋含み（プラスは緑・マイナスは赤）", HTML)

    def test_heading_says_the_size_and_lists_the_holds(self):
        self.assertIn("で入った場合）　きのう15:25に入り、今日14:00に決済　合計 ", HTML)
        self.assertIn("onClosed=Array.isArray(p.overnight_closed)?p.overnight_closed:[];", HTML)
        self.assertIn('<div class="cap-on-list">', HTML)
        self.assertIn("資金の大きさで入れた銘柄の数が変わります。", HTML)


if __name__ == "__main__":
    unittest.main()
