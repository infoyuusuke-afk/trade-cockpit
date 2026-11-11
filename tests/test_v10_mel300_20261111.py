"""OWNER 2026-11-11 「メルに任せる300万を、今の300万とは別の仮想口座で作って。決めた内容は寄り前に記録、後から変えない」「メル口座 OK」.
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


def plan(day, **kw):
    p = {"schema": "MEL_PLAN_V1", "date": day, "methods": ["R4", "ON_LONG"], "size_pct": 50, "max_mult": 2.0,
         "overnight": True, "daily_stop_pct": 2.0, "reason": "テスト"}
    p.update(kw)
    return p


class MelAccount(unittest.TestCase):
    def setUp(self):
        live._MEL_MEMO.clear()
        live._AIR_MEMO.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        self.rec = self.run / "records"
        self.rec.mkdir()
        (self.run / live.MEL_DIR).mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_plan(self, day, p):
        f = self.run / live.MEL_DIR / ("plan_%s.json" % day)
        f.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
        return f

    def test_check(self):
        ok, why = live.mel_plan_check(plan("2026-11-12"), "2026-11-12")
        self.assertIsNone(why)
        self.assertEqual(ok["methods"], ["R4", "ON_LONG"])
        for bad in (plan("2026-11-13"), plan("2026-11-12", methods=["BUY_ALL"]), plan("2026-11-12", size_pct=5),
                    plan("2026-11-12", max_mult=4), plan("2026-11-12", daily_stop_pct=50), plan("2026-11-12", overnight="yes"),
                    plan("2026-11-12", schema="X"), [1]):
            self.assertIsNone(live.mel_plan_check(bad, "2026-11-12")[0])

    def test_lock_before_9_and_never_changed_after(self):
        day = self.rec / "2026-11-12"
        f = self.write_plan("2026-11-12", plan("2026-11-12"))
        got = live.mel_lock(self.run, day, "2026-11-12", "08:41")
        self.assertEqual(got["state"], "決定")
        self.assertEqual(got["plan"]["size_pct"], 50)
        f.write_text(json.dumps(plan("2026-11-12", size_pct=100)), encoding="utf-8")   # rewritten after the lock
        again = live.mel_lock(self.run, day, "2026-11-12", "10:00")
        self.assertEqual(again["plan"]["size_pct"], 50)
        out = live.mel300(self.rec, self.run, day, "2026-11-12", "10:00")
        self.assertTrue(out["changed_after_lock"])
        self.assertEqual(out["today_plan"]["plan"]["size_pct"], 50)

    def test_no_plan_by_9_is_a_rest_day_and_a_late_plan_is_not_used(self):
        day = self.rec / "2026-11-12"
        self.assertIsNone(live.mel_lock(self.run, day, "2026-11-12", "08:50"))   # not written yet: look again
        got = live.mel_lock(self.run, day, "2026-11-12", "09:00")
        self.assertEqual((got["state"], got["plan"]), ("休み", None))
        self.write_plan("2026-11-12", plan("2026-11-12"))
        self.assertEqual(live.mel_lock(self.run, day, "2026-11-12", "09:10")["state"], "休み")

    def test_half_written_plan_is_read_again(self):
        f = self.run / live.MEL_DIR / "plan_2026-11-12.json"
        f.write_text('{"schema":"MEL_PL', encoding="utf-8")
        self.assertIsNone(live.mel_lock(self.run, self.rec / "2026-11-12", "2026-11-12", "08:31"))
        self.write_plan("2026-11-12", plan("2026-11-12"))
        self.assertEqual(live.mel_lock(self.run, self.rec / "2026-11-12", "2026-11-12", "08:32")["state"], "決定")

    def test_bad_plan_is_a_rest_day(self):
        self.write_plan("2026-11-12", plan("2026-11-12", size_pct=500))
        got = live.mel_lock(self.run, self.rec / "2026-11-12", "2026-11-12", "08:40")
        self.assertEqual((got["state"], got["why"]), ("休み", "額か上限が範囲の外"))

    def test_replay_follows_each_days_plan(self):
        # 11/12: plan R4 only, 50%, overnight yes (ON_LONG); 11/13: rest day (no plan) - the 11/12 overnight still ends on 11/13
        for d, p in (("2026-11-12", plan("2026-11-12")),):
            self.write_plan(d, p)
            live.mel_lock(self.run, self.rec / d, d, "08:40")
        live.mel_lock(self.run, self.rec / "2026-11-13", "2026-11-13", "09:01")
        d1 = self.rec / "2026-11-12"
        (d1 / live.OWNER_RULES_FILE).write_text(json.dumps({"trades": [
            {"ticker": "1111.T", "name": "a", "rule": "R4", "status": "CLOSED", "fill_time": "09:20:00", "exit_time": "09:40:00", "yen": 1000},
            {"ticker": "2222.T", "name": "b", "rule": "R5", "status": "CLOSED", "fill_time": "09:30:00", "exit_time": "09:50:00", "yen": 5000}]}),
            encoding="utf-8")
        (d1 / live.RULE_SIGNALS_FILE).write_text("captured_at,ticker,name,signal,strategy,signal_bar,rule,entry,target,stop\n"
                                                 "2026-11-12 09:19:30,1111.T,a,買いサイン,s,b,R4,1000,1010,990\n"
                                                 "2026-11-12 09:29:30,2222.T,b,空売りサイン,s,b,R5,1000,990,1010\n", encoding="utf-8")
        (self.run / live.HISTORY_FILE).write_text("\n".join([HIST_HEAD,
            '"2026-11-12","t","1","3333.T","c","LONG","70","1000","1000","2026-11-12","2026-11-13","","","","","","2","","","勝ち","検証済み"',
            '"2026-11-12","t","2","4444.T","e","SHORT","70","1000","1000","2026-11-12","2026-11-13","","","","","","9","","","勝ち","検証済み"',
            '"2026-11-11","t","1","5555.T","f","LONG","70","1000","1000","2026-11-11","2026-11-12","","","","","","9","","","勝ち","検証済み"']) + "\n",
            encoding="utf-8")
        out = live.mel300(self.rec, self.run, self.rec / "2026-11-16", "2026-11-16", "08:00")
        self.assertEqual(out["from"], "2026-11-12")
        self.assertFalse(out["real_submit_allowed"])
        days = {r[0]: r for r in out["days"]}
        self.assertEqual(days["2026-11-12"][1], 1000 * 1500 // 100)   # R4 only (R5 not chosen); 150万 = 1,500 shares
        self.assertEqual(days["2026-11-12"][3], 1)                    # 5555 was decided 11/11, before any plan: not entered
        on = days["2026-11-13"]
        self.assertEqual(on[3], 1)                                    # only the long (ON_SHORT not chosen on 11/12)
        self.assertGreater(on[1], 0)
        self.assertEqual([p[1] for p in out["plans"]], ["決定", "休み"])
        self.assertEqual([t[6] for t in out["trades"]], ["R4", "ON_LONG"])

    def test_daily_stop(self):
        self.write_plan("2026-11-12", plan("2026-11-12", daily_stop_pct=1.0, size_pct=100, max_mult=3.3))
        live.mel_lock(self.run, self.rec / "2026-11-12", "2026-11-12", "08:40")
        d1 = self.rec / "2026-11-12"
        (d1 / live.OWNER_RULES_FILE).write_text(json.dumps({"trades": [
            {"ticker": "1111.T", "name": "a", "rule": "R4", "status": "CLOSED", "fill_time": "09:20:00", "exit_time": "09:30:00", "yen": -2000},
            {"ticker": "2222.T", "name": "b", "rule": "R4", "status": "CLOSED", "fill_time": "09:40:00", "exit_time": "09:50:00", "yen": 3000}]}),
            encoding="utf-8")
        (d1 / live.RULE_SIGNALS_FILE).write_text("captured_at,ticker,name,signal,strategy,signal_bar,rule,entry,target,stop\n"
                                                 "2026-11-12 09:19:30,1111.T,a,買いサイン,s,b,R4,1000,1010,990\n"
                                                 "2026-11-12 09:39:30,2222.T,b,買いサイン,s,b,R4,1000,1010,990\n", encoding="utf-8")
        out = live.mel300(self.rec, self.run, self.rec / "2026-11-13", "2026-11-13", "08:00")
        r = out["days"][0]
        self.assertEqual((r[1], r[3], r[5]), (-60000, 1, "09:40"))   # −6万 (2% of 300万) is past the 1% line: the 2nd is not entered

    def test_today_live_follows_the_plan(self):
        # 「売買銘柄、タイミングはリアルタイム監視できる形に」: today's trades as they happen, by today's fixed plan
        self.write_plan("2026-11-12", plan("2026-11-12", methods=["R4"], size_pct=50, daily_stop_pct=None))
        lock = live.mel_lock(self.run, self.rec / "2026-11-12", "2026-11-12", "08:40")
        trades = [
            {"kind": "day", "rule": "R4", "ticker": "1111.T", "name": "a", "side": 1, "fill": 1000.0, "in": "09:20", "out": "09:40",
             "ret": 1.0, "exit": 1010.0, "last": 1010.0, "ticks": []},
            {"kind": "day", "rule": "R5", "ticker": "2222.T", "name": "b", "side": -1, "fill": 1000.0, "in": "09:30", "out": None,
             "ret": None, "exit": None, "last": 990.0, "ticks": []},
            {"kind": "day", "rule": "R4", "ticker": "3333.T", "name": "c", "side": 1, "fill": 2000.0, "in": "10:00", "out": None,
             "ret": None, "exit": None, "last": 1990.0, "ticks": []}]
        got = live.mel_today(self.rec, trades, lock, {"from": None, "days": []}, "10:05")
        self.assertEqual(got["state"], "OK")
        self.assertEqual([r["name"] for r in got["rows"]], ["a", "c"])          # R5 not chosen
        a, c = got["rows"]
        self.assertEqual((a["shares"], a["done_yen"], a["out"]), (1500, 15000, "09:40"))
        self.assertEqual((c["shares"], c["open_yen"], c["out"]), (700, -7000, None))
        self.assertEqual((got["done"], got["open"]), (15000, -7000))
        self.assertEqual(live.mel_today(self.rec, trades, None, {"from": None, "days": []}, "10:05")["state"], "まだ始まっていません")

    def test_safe_and_screen(self):
        orig = live.mel300
        try:
            live.mel300 = lambda *a: 1 / 0
            got = live._mel300_safe(Path("."), Path("."), Path("."), "2026-11-12", "08:00")
        finally:
            live.mel300 = orig
        self.assertEqual(got["state"], "UNAVAILABLE")
        self.assertIn('"mel300": _mel300_safe(records, day_dir.parent.parent, day_dir, today, now_hm, trades),',
                      (ROOT / "scripts" / "v10_positions_live.py").read_text(encoding="utf-8"))
        self.assertIn("function melHtml(){", HTML)
        self.assertIn("メル口座（任せる300万・仮想）", HTML)
        self.assertIn("function melLiveHtml(){", HTML)
        # 「今夜決算の札はカードの中に入れて」: the label inside its own card, framed red
        self.assertIn("return tag?String(card).replace(", HTML)
        self.assertIn(".earn-card{outline:2px dashed #b47cff!important;outline-offset:-2px}", HTML)   # not red: red is 空売り
        self.assertIn("<div class=\"earn-tag\">📅 決算またぎ　", HTML)
        self.assertIn('const want=["virt-day-line","virt-held-line","mel-live","cap-area","trade-fx-link"].map(id=>document.getElementById(id)).filter(Boolean);', HTML)   # in トレード中 「仮想の成績」


if __name__ == "__main__":
    unittest.main()
