"""OWNER 2026-10-27 「ショートリバの初動検知（大きく下げた銘柄で、大きい買いの約定・売り板が薄くなる・安値を割らない）を記録と
表示と声だけで作って、その後の戻りを毎日集計して」. Synthetic rows only."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest

from scripts import v10_positions_live as pos

ROOT = Path(__file__).resolve().parents[1]


def snap(t, price, vol, ask=None, ask_qty=1000, over=100000, vwap=1000.0, ticker="A.T"):
    return {"captured_at": "2026-10-27 " + t, "ticker": ticker, "name": "名A（0000）", "price": str(price), "volume": str(vol),
            "vwap": str(vwap), "ask": str(ask if ask is not None else price + 1), "ask_qty": str(ask_qty), "over": str(over)}


def falling_day(det, *, big=60000, ask_qty=300, rebound=True):
    """High 1000 at 10:00, steady fall to 950 by 10:10, flat for 6 minutes, then a big buy at the ask with a thin ask."""
    rows, vol, sec = [], 0, 10 * 3600
    price = 1000.0
    for i in range(80):
        t = "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)
        vol += 1000
        price = max(950.0, 1000.0 - i)
        rows.append(snap(t, price, vol))
        sec += 12
    t = "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)
    rows.append(snap(t, 951, vol + big, ask_qty=ask_qty))
    for r in rows:
        det.feed(r)
    later = [("11:00:00", 970), ("13:00:00", 960), ("15:20:00", 955)] if rebound else []
    for t, p in later:
        vol += big + 1000
        det.feed(snap(t, p, vol))
    return det


class Detector(unittest.TestCase):
    def test_all_four_conditions_make_one_first_move_and_it_is_followed_to_1520(self):
        det = falling_day(pos.ReboundDetector())
        self.assertEqual(len(det.signals), 1)
        s = det.signals[0]
        self.assertLessEqual(s["drop_from_high_pct"], -4)
        self.assertGreaterEqual(s["volume_x"], 5)
        o = det.outcomes()[0]
        self.assertEqual((o["peak"], o["peak_at"]), (970.0, "11:00:00"))
        self.assertTrue(o["final"])
        self.assertAlmostEqual(o["fall_from_peak_pct"], (955 / 970 - 1) * 100, places=2)
        self.assertEqual(pos.rebound_summary(det.outcomes())["n"], 1)

    def test_second_stage_top_is_a_short_candidate_with_the_rebound_high_as_stop(self):
        # OWNER 2026-10-27 「2段の合図（初動＝まだ売るな、上がり切り＝ショート候補と損切りの目安）」
        det = falling_day(pos.ReboundDetector(), rebound=False)
        vol = 200000
        for t, p in (("10:20:00", 955), ("10:30:00", 962), ("10:31:00", 961), ("10:34:00", 958), ("15:20:00", 950)):
            vol += 1000
            det.feed(snap(t, p, vol))
        self.assertEqual(len(det.tops), 1)
        top = det.tops[0]
        self.assertEqual((top["price"], top["stop"], top["top_at"][11:]), (958.0, 962.0, "10:34:00"))
        o = det.outcomes()[0]["top"]
        self.assertIsNone(o["stopped_at"])
        self.assertAlmostEqual(o["short_pct"], (1 - 950 / 958) * 100, places=2)
        self.assertEqual(pos.rebound_summary(det.outcomes())["tops"]["n"], 1)

    def test_top_is_stopped_at_the_rebound_high(self):
        det = falling_day(pos.ReboundDetector(), rebound=False)
        vol = 200000
        for t, p in (("10:30:00", 962), ("10:34:00", 958), ("10:40:00", 963), ("15:20:00", 940)):
            vol += 1000
            det.feed(snap(t, p, vol))
        o = det.outcomes()[0]["top"]
        self.assertEqual(o["stopped_at"], "10:40:00")
        self.assertAlmostEqual(o["short_pct"], (1 - 962 / 958) * 100, places=2)

    def test_no_big_buy_or_no_thin_ask_means_no_signal(self):
        self.assertEqual(falling_day(pos.ReboundDetector(), big=2000).signals, [])
        self.assertEqual(falling_day(pos.ReboundDetector(), ask_qty=1000).signals, [])

    def test_lunch_break_volume_is_not_a_big_buy(self):
        det = pos.ReboundDetector()
        vol = 0
        for i in range(30):
            vol += 1000
            det.feed(snap("11:2%d:%02d" % (i // 5, i % 5 * 12), 950 if i > 5 else 1000 - i * 10, vol))
        det.feed(snap("12:30:05", 951, vol + 90000, ask_qty=100))
        self.assertEqual(det.signals, [])

    def test_build_records_the_day_and_the_past_summary(self):
        tmp = Path(tempfile.mkdtemp(prefix="v10-sr-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        day = tmp / "records" / "2026-10-27"
        day.mkdir(parents=True)
        rows = []
        det = pos.ReboundDetector()
        orig = det.feed
        det.feed = lambda r: (rows.append(r), orig(r))[1]
        falling_day(det, rebound=False)
        fields = list(rows[0].keys())
        with open(day / pos.SNAPSHOTS_FILE, "w", encoding="utf-8-sig", newline="") as f:
            import csv
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        old = tmp / "records" / "2026-10-26"
        old.mkdir()
        (old / pos.REBOUND_OUTCOMES_FILE).write_text(json.dumps({"outcomes": [
            {"detected_at": "2026-10-26 10:00:00", "rebound_pct": 1.0, "minutes_to_peak": 30, "fall_from_peak_pct": -2.0,
             "end_pct": -1.0, "low_broken": True, "final": True}]}), encoding="utf-8")
        state = {}
        v = pos._short_rebound(day, tmp / "records", "2026-10-27", state)
        self.assertEqual(v["today_count"], 1)
        self.assertEqual(v["summary_past"]["n"], 1)
        self.assertTrue((day / pos.REBOUND_SIGNALS_FILE).is_file())
        pos._short_rebound(day, tmp / "records", "2026-10-27", state)   # no duplicate line on the next pass
        self.assertEqual(len(pos._rows(day / pos.REBOUND_SIGNALS_FILE)), 1)


def _block():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert '<div id="short-rebound-alert" class="short-rebound-alert" hidden></div></div>' in html
    return html.split('const box=document.getElementById("short-rebound-alert");', 1)[1].split("</script>", 1)[0]


class Screen(unittest.TestCase):
    def test_box_shows_both_stages_and_speaks_each_new_one_at_most_8_a_day(self):
        b = _block()
        assert 'bp.positions&&bp.positions.short_rebound' in b
        assert 'if(st.first.length<=8)say("ショートリバ初動。"+short(r.name)+"。まだ売らない。")' in b
        assert 'if(st.top.length<=8)say("ショートリバ上がり切り。"+short(t.name)+"。ショート候補。損切りの目安、"+t.stop+"円。")' in b
        assert "sr.tops_today" in b and "売買の合図ではありません" in b
        assert "0件とは扱いません" in b and "order" not in b.lower().replace("no order", "")


if __name__ == "__main__":
    unittest.main()
