"""OWNER 2026-11-11 「AIコクピットはかえない　AIトレード日記タブに資金３００万からスタートした場合のエアトレードを追加」.
Synthetic data only; virtual, display only, no MS2, no orders."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v10_positions_live as live  # noqa: E402

HTML = (ROOT / "index.html").read_text(encoding="utf-8")
HIST_HEAD = '"decision_date","finalized_at","rank","ticker","name","side","hold_score","reference_price_1525","entry_close_price","entry_date","evaluation_date","next_open","next_close","next_high","next_low","return_open_pct","return_close_pct","mfe_pct","mae_pct","result","status"'


class Air300(unittest.TestCase):
    def setUp(self):
        live._AIR_MEMO.clear()

    def _build(self, tmp: Path):
        rec = tmp / "records"
        d1 = rec / "2026-11-04"
        d1.mkdir(parents=True)
        (d1 / live.OWNER_RULES_FILE).write_text(json.dumps({"trades": [
            {"ticker": "1111.T", "rule": "R4", "status": "CLOSED", "fill_time": "09:20:00", "exit_time": "09:40:00", "yen": 1000},
            {"ticker": "2222.T", "rule": "R4", "status": "OPEN", "fill_time": "10:00:00", "exit_time": None, "yen": None}]}), encoding="utf-8")
        (d1 / live.RULE_SIGNALS_FILE).write_text("captured_at,ticker,name,signal,strategy,signal_bar,rule,entry,target,stop\n"
                                                 "2026-11-04 09:19:30,1111.T,x,買いサイン,s,b,R4,1000,1010,990\n", encoding="utf-8")
        (tmp / live.HISTORY_FILE).write_text("\n".join([HIST_HEAD,
            '"2026-11-04","t","1","3333.T","y","LONG","70","2000","2000","2026-11-04","2026-11-05","","","","","","-1.0","","","負け","検証済み"',
            '"2026-11-06","t","1","4444.T","z","SHORT","70","500","500","2026-11-06","2026-11-08","","","","","","5","","","勝ち","検証済み"',
            '"2026-11-10","t","1","5555.T","w","LONG","70","100","100","2026-11-10","2026-11-11","","","","","","3","","","勝ち","検証済み"']) + "\n",
            encoding="utf-8")
        today = rec / "2026-11-11"
        today.mkdir()
        return rec, today

    def test_replay_grows_from_300man_and_skips_today_and_weekends(self):
        with tempfile.TemporaryDirectory() as d:
            rec, today = self._build(Path(d))
            a = live.air300(rec, Path(d), today, "2026-11-11")
            self.assertTrue((today / live.AIR_FILE).is_file())
            again = live.air300(rec, Path(d), today, "2026-11-11")
        self.assertEqual(a, again)
        self.assertEqual(a["start"], 3_000_000)
        self.assertFalse(a["real_submit_allowed"])
        self.assertEqual([r[0] for r in a["days"]], ["2026-11-04", "2026-11-05"])   # 11/08 (Sunday) moves to 11/09, which has no ticks; 11/11 is today
        d1, d2 = a["days"]
        self.assertEqual(d1[1], 1000 * 3000 // 100)      # 3,000 shares (300万 / 1,000円) of the 100-share yen
        self.assertEqual(d1[2], 3_000_000 + 30_000)
        self.assertEqual(d2[3], 1)                       # one overnight long, 1,500 shares at 2,000円 (room for one more trade is left)
        self.assertLess(d2[1], -30000)                   # −1% of 300万 and one day of interest
        self.assertEqual(a["by_rule"]["R4"], [30000, 1, 1])
        self.assertEqual(a["peak"], 3_030_000)
        # 「トレード履歴を追加」: one row per trade taken (day, decided, in, out, name, side, rule, shares, amount, yen)
        self.assertEqual(a["trades"][0], ["2026-11-04", "", "09:20", "09:40", "1111.T", 1, "R4", 3000, 3_000_000, 30000])
        self.assertEqual(a["trades"][1][:7], ["2026-11-05", "2026-11-04", "09:00", "14:00", "y", 1, "ON_LONG"])
        self.assertEqual(len(a["trades"]), 2)
        self.assertEqual(a["weekend_moved_unpriced"], 1)

    def test_weekend_stamped_pick_is_priced_on_the_next_weekday(self):
        # OWNER 2026-11-11 「どこが違うか一行ずつ照らして、正しい方に1本化」: the Friday pick stamped on Sunday 11/08
        with tempfile.TemporaryDirectory() as d:
            rec, today = self._build(Path(d))
            mon = rec / "2026-11-09"
            mon.mkdir()
            (mon / live.TICKS_FILE).write_text("captured_at,ticker,name,exchange_time,price\n"
                                               "2026-11-09 09:00:04.5,4444.T,z,15:24:59,999\n"        # Friday's close seen at 09:00: dropped
                                               "2026-11-09 15:00:00.0,4444.T,z,14:59:59,450\n"
                                               "2026-11-09 15:30:05.0,4444.T,z,15:30:00,440\n", encoding="utf-8")
            a = live.air300(rec, Path(d), today, "2026-11-11")
        self.assertEqual([r[0] for r in a["days"]], ["2026-11-04", "2026-11-05", "2026-11-09"])
        self.assertEqual(a["weekend_moved_unpriced"], 0)
        t = [x for x in a["trades"] if x[0] == "2026-11-09"][0]
        self.assertEqual(t[:7], ["2026-11-09", "2026-11-06", "09:00", "14:00", "z", -1, "ON_SHORT"])
        self.assertGreater(t[9], 0)                      # short from 500 to 440 (12%) minus 3 days of interest
        sh = t[7]
        self.assertAlmostEqual(t[9], round((0.12 * 100 - 0.011 * 3 / 365 * 100) / 100 * 500 * sh), delta=1)

    def test_memo_once_a_day_without_the_day_folder(self):
        with tempfile.TemporaryDirectory() as d:
            rec, today = self._build(Path(d))
            missing = rec / "2026-11-12"
            a = live.air300(rec, Path(d), missing, "2026-11-12")
            (rec / "2026-11-04" / live.OWNER_RULES_FILE).write_text("{}", encoding="utf-8")
            self.assertEqual(live.air300(rec, Path(d), missing, "2026-11-12"), a)   # not recomputed the same day

    def test_broken_files_never_break_the_capital_view(self):
        # audit 0f33e32: a non-numeric yen and a list at the top level
        with tempfile.TemporaryDirectory() as d:
            rec, today = self._build(Path(d))
            f = rec / "2026-11-04" / live.OWNER_RULES_FILE
            f.write_text(json.dumps({"trades": [{"ticker": "1111.T", "rule": "R4", "status": "CLOSED", "fill_time": "09:20:00",
                                                 "exit_time": "09:40:00", "yen": "abc"}, "x",
                                                {"ticker": "1111.T", "rule": "R4", "status": "CLOSED", "fill_time": "09:20:00",
                                                 "exit_time": "09:40:00", "yen": "inf"}]}), encoding="utf-8")
            a = live.air300(rec, Path(d), today, "2026-11-12")
            self.assertEqual([r[0] for r in a["days"]], ["2026-11-05", "2026-11-11"])
            f.write_text("[1, 2]", encoding="utf-8")
            (today / live.AIR_FILE).unlink(missing_ok=True)
            self.assertEqual(live.air300(rec, Path(d), today, "2026-11-11")["days"][0][0], "2026-11-05")
        orig = live.air300
        try:
            live.air300 = lambda *a: 1 / 0
            got = live._air300_safe(Path("."), Path("."), Path("."), "2026-11-11")
        finally:
            live.air300 = orig
        self.assertEqual((got["state"], got["reason"], got["days"]), ("UNAVAILABLE", "ZeroDivisionError", []))

    def test_diary_tab_shows_it(self):
        self.assertIn('"air300": _air300_safe(records, day_dir.parent.parent, day_dir, today),', (ROOT / "scripts" / "v10_positions_live.py").read_text(encoding="utf-8"))
        self.assertIn("function airHtml(){", HTML)
        self.assertIn("function airTrades(a){", HTML)
        self.assertIn('<table class="air-tbl" data-keep-table>', HTML)   # the card adapter must leave the history as a table
        self.assertIn('sec.addEventListener("toggle",e=>{const d=e.target;if(!d.dataset||!d.dataset.airday||!airOpen)return;', HTML)
        self.assertIn("エアトレード（資金300万から・メル・仮想）", HTML)
        self.assertIn("資金の大きさで入れた銘柄の数が変わります。</p></div>'+airHtml();", HTML)


if __name__ == "__main__":
    unittest.main()
