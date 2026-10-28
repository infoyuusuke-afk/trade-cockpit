"""Methods on trial (試験中): per-method virtual trades from synthetic ticks only. No orders, no signals."""
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import v10_trial_methods as tm

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
HEAD = "captured_at,ticker,name,exchange_time,price,direction_estimate,bid,ask,note\n"


def tick(t, ticker, price):
    return '"2026-10-29 %s.000","%s","n","%s","%s","UNKNOWN","","",""\n' % (t, ticker, t, price)


class TrialMethods(unittest.TestCase):
    def setUp(self):
        self.rt = Path(tempfile.mkdtemp(prefix="v10-trial-"))
        self.addCleanup(shutil.rmtree, self.rt, True)
        self.day = self.rt / "records" / "2026-10-29"
        self.day.mkdir(parents=True)

    def write(self, rows, inputs=True, ai=()):
        (self.day / tm.TICKS_FILE).write_text(HEAD + "".join(rows), encoding="utf-8-sig")
        if inputs:
            t = {"1111": {"prev_close": 1000, "ma25": 1300, "dev_pct": -23.1},
                 "2222": {"prev_close": 1000, "ma25": 1000, "dev_pct": 0.0},
                 "3333": {"prev_close": 1000, "ma25": 1000, "dev_pct": 0.0}}
            (self.rt / tm.INPUT_FILE).write_text(json.dumps({
                "schema_version": tm.INPUT_SCHEMA, "for_date": "2026-10-29", "tickers": t, "ai_methods": list(ai),
                "real_submit_allowed": False}, ensure_ascii=False), encoding="utf-8")

    def build(self, hm="16:00"):
        h, m = map(int, hm.split(":"))
        return tm.build(self.rt, now=datetime(2026, 10, 29, h, m, tzinfo=JST), state={})

    def by(self, view):
        return {m["method"]: m for m in view["today"]}

    def test_day_trade_1_and_2_and_ep(self):
        self.write([
            # 1111: deep under the 25-day line, opens -1 % -> DT1 buys at the 10:00 price 995, sold at the last print 1010
            tick("09:00:01", "1111.T", 990), tick("09:59:58", "1111.T", 995), tick("15:24:59", "1111.T", 1010),
            # 2222: -4 % at 11:30 but +1 % above the open -> DT2 buys 960, the stop -2 % (940.8) is hit at 13:00
            tick("09:00:02", "2222.T", 950), tick("11:29:59", "2222.T", 960), tick("13:00:00", "2222.T", 940),
            tick("15:20:00", "2222.T", 950),
            # 3333: opens +12 % -> EP buys the open 1120
            tick("09:00:03", "3333.T", 1120), tick("15:25:00", "3333.T", 1150),
        ], ai=["勝ち型_EP 10%以上GUを寄りで買い→5日後の引け", "勝ち型_BNF 25日線−20%買い"])
        v = self.build()
        m = self.by(v)
        t1 = m["DT1"]["trades"][0]
        self.assertEqual((t1["ticker"], t1["entry"], t1["exit"], t1["how"], t1["status"]), ("1111.T", 995, 1010, "引け", "CLOSED"))
        self.assertEqual(t1["yen"], round(((1010 / 995 - 1) * 100 - 0.10) / 100 * 995 * 100))
        t2 = m["DT2"]["trades"][0]
        self.assertEqual((t2["ticker"], t2["entry"], t2["exit"], t2["how"]), ("2222.T", 960, 940, "損切り"))
        ep = m["EP"]["trades"][0]
        self.assertEqual((ep["ticker"], ep["entry"], ep["status"], ep["hold"], ep["stop"]), ("3333.T", 1120, "OPEN", 10, 0.08))
        self.assertIn("AI:勝ち型_EP 10%以上GUを寄りで買い→5日後の引け", m)
        self.assertEqual(v["ai_not_runnable"], ["勝ち型_BNF 25日線−20%買い"])
        self.assertIs(v["real_submit_allowed"], False)
        self.assertIs(v["trade_instruction"], False)
        self.assertEqual(v["history"]["DT1"]["n"], 1)
        pos = json.loads((self.rt / tm.POS_FILE).read_text(encoding="utf-8"))["positions"]
        self.assertEqual({p["method"] for p in pos}, {"EP", "AI:勝ち型_EP 10%以上GUを寄りで買い→5日後の引け"})

    def test_no_inputs_no_day_trade_1(self):
        self.write([tick("09:00:01", "1111.T", 990), tick("09:59:58", "1111.T", 995), tick("15:24:59", "1111.T", 1010)],
                   inputs=False)
        v = self.build()
        self.assertEqual(self.by(v)["DT1"]["trades"], [])
        self.assertTrue(v["notes"])

    def test_minus_30000_yen_stops_the_method_for_the_day(self):
        cands = [{"ticker": "A.T", "entry_time": "11:30:00", "entry": 20000, "stop_pct": 0.02},
                 {"ticker": "B.T", "entry_time": "11:30:00", "entry": 20000, "stop_pct": 0.02},
                 {"ticker": "C.T", "entry_time": "13:00:00", "entry": 1000, "stop_pct": 0.02}]
        ticks = {"A.T": [("11:30:00", 20000), ("12:31:00", 19000)], "B.T": [("11:30:00", 20000), ("12:40:00", 19000)],
                 "C.T": [("13:00:00", 1000), ("15:20:00", 1100)]}
        r = tm.settle_day("DT2", cands, ticks, "16:00:00")
        self.assertEqual(r["limit_hit_at"], "12:31:00")          # A alone loses about 102,000 yen at 12:31
        self.assertEqual([t["status"] for t in r["trades"]], ["CLOSED", "CLOSED", "止め（−3万円）"])
        b_ = r["trades"][1]                                       # B was still held at 12:31: closed then
        self.assertEqual((b_["exit_time"], b_["exit"], b_["how"]), ("12:31:00", 20000, "止め（−3万円）"))


class Wiring(unittest.TestCase):
    def test_observer_pin_gateway_and_panel(self):
        import scripts.ai_brain_observer as obs
        name, pin = obs.TRIAL_MODULE
        self.assertEqual(obs.git_blob_sha1((ROOT / "scripts" / (name + ".py")).read_bytes()), pin)
        gw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/trial_methods.json') {", gw)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-trial-methods-v1'", gw)
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('fetch("/trial_methods.json?t="+Date.now(),{cache:"no-store"})', html)
        self.assertIn("試験中の手法（仮想・100株・成績だけ）", html)
        block = html.split("// OWNER 2026-10-28 「コクピットの仮想売買は、今の①〜⑤も残したまま", 1)[1].split("})();", 1)[0]
        for banned in ("cockpitSpeak", "speechSynthesis", "RssOrder", "renderAttention"):
            self.assertNotIn(banned, block)


if __name__ == "__main__":
    unittest.main()
