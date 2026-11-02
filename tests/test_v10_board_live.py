"""SCALP8 board panel / 板 tab (OWNER 2026-11-02). Synthetic records only; display only, never a trade signal."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from scripts import v10_board_live as bl

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
DAY = "2026-11-02"


def hms(s):
    return "%02d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60)


def board_row(s, bid1_qty=100):
    vals = []
    for i in range(1, 11):
        vals += [1000 + i, 100, 1001 - i, bid1_qty if i == 1 else 100]
    return ",".join(["%s %s.000" % (DAY, hms(s)), "1111", "1"] + [str(v) for v in vals])


def write_day(d):
    rec = Path(d) / "records" / DAY
    rec.mkdir(parents=True)
    hdr = ["captured_at", "ticker", "read_seq"] + [k % i for i in range(1, 11) for k in ("ask%d", "ask_qty%d", "bid%d", "bid_qty%d")]
    rows = [",".join(hdr)] + [board_row(s, 1000 if 32460 <= s < 32470 else 100) for s in range(32400, 32581)]
    (rec / "scalp8_board.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    t = ["captured_at,ticker,exchange_time,price,volume,side_estimate,best_bid,best_ask,read_seq,batch",
         "%s 08:50:00.000,1111,15:24:00,990,100,,,,1,initial" % DAY]           # first read: skipped
    for s in range(32400, 32601):                                                # 09:00:00 = the auction, then 200 prints
        t.append("%s %s.500,1111,%s,1002,100,BUY,1000,1002,2,gap" % (DAY, hms(s), hms(s)))
    t.append("%s 09:03:21.500,1111,09:03:20,1002,100,BUY,1000,1002,3,gap" % DAY)   # the same print read again: skipped
    t.append("%s 09:03:22.000,1111,15:24:00,1002,99999,SELL,1000,1002,3," % DAY)   # previous day's print: skipped
    t.append("%s 09:03:30.000,1111,09:03:30,1002,5000,SELL,1000,1002,4," % DAY)     # a big print
    (rec / "scalp8_ticks.csv").write_text("\n".join(t) + "\n", encoding="utf-8")
    (rec / "under_over.csv").write_text('captured_at,ticker,name,price,over,under,under_ratio,over_under_change,vwap\n'
                                        '"%s 09:03:00","1111.T","テスト（1111）","1002","3000","1000","0.25","0","1001"\n' % DAY, encoding="utf-8")
    (rec / "absorb_voice.csv").write_text("rang_at,ticker,name,sold_into_bid_60s,median_volume_per_minute,times,price_at_start,last_price,voice\n"
                                          "%s 09:03:40,1111,テスト,5000,500,10.0,1002,1002,吸収\n" % DAY, encoding="utf-8")


class BoardLive(unittest.TestCase):
    def build(self):
        d = tempfile.mkdtemp()
        write_day(d)
        st = {}
        view = bl.build(d, now=datetime(2026, 11, 2, 9, 5, tzinfo=JST), state=st)
        return d, st, view

    def test_view_flags_and_file(self):
        d, st, view = self.build()
        self.assertEqual(view["schema_version"], "100b-v10-scalp8-board-v1")
        self.assertIs(view["real_submit_allowed"], False)
        self.assertIs(view["trade_instruction"], False)
        self.assertIs(view["unverified"], True)
        self.assertEqual(json.loads((Path(d) / bl.OUT_FILE).read_text(encoding="utf-8")), json.loads(json.dumps(view)))
        s = view["stocks"][0]
        self.assertEqual((s["code"], s["name"], s["last_price"]), ("1111", "テスト（1111）", 1002))
        self.assertEqual((s["over"], s["under"], s["under_ratio"]), (3000, 1000, 0.25))
        self.assertEqual((s["bid5"], s["ask5"], s["buy_ratio"], s["spread"]), (500, 500, 0.5, 1.0))
        self.assertEqual(len(s["levels"]), 10)
        self.assertEqual(s["absorb"][0]["at"], "09:03:40")

    def test_prints_initial_gap_and_previous_day_are_skipped(self):
        d, st, view = self.build()
        sk = st["stocks"]["1111"]
        self.assertEqual(sk["am_open"], 32400)
        self.assertEqual(len(sk["vols"]), 201)                   # 200 continuous prints + the big one, nothing else
        self.assertNotIn(99999, sk["vols"])

    def test_big_print(self):
        d, st, view = self.build()
        s = view["stocks"][0]
        self.assertEqual(s["big_threshold"], 1000)
        self.assertEqual(s["big"], [{"at": "09:03:30", "price": 1002, "qty": 5000, "side": "売り"}])

    def test_wall_that_vanishes_without_prints(self):
        d, st, view = self.build()
        s = view["stocks"][0]
        self.assertEqual(s["vanished"], [{"at": "09:01:00", "side": "買い", "price": 1000, "qty": 900, "traded": 0}])
        self.assertEqual(s["walls"], [])                          # the last board has no wall
        self.assertEqual(s["usual_level_qty"], 100)

    def test_ratio_history_only_continuous_minutes(self):
        d, st, view = self.build()
        hist = dict(view["stocks"][0]["ratio_hist"])
        self.assertEqual(sorted(hist), ["09:00", "09:01", "09:02", "09:03"])
        self.assertEqual(hist["09:02"], 0.5)

    def test_incremental_and_new_day(self):
        d, st, view = self.build()
        again = bl.build(d, now=datetime(2026, 11, 2, 9, 5, 5, tzinfo=JST), state=st)
        self.assertEqual(again["stocks"], view["stocks"])         # nothing new read twice
        nxt = bl.build(d, now=datetime(2026, 11, 3, 9, 0, tzinfo=JST), state=st)
        self.assertEqual(nxt["stocks"], [])

    def test_board_waits_while_prints_catch_up(self):
        d = tempfile.mkdtemp()
        write_day(d)
        old = bl.MAX_READ_BYTES
        try:
            bl.MAX_READ_BYTES = 70000
            ticks = Path(d) / "records" / DAY / "scalp8_ticks.csv"
            with open(ticks, "a", encoding="utf-8") as f:
                f.write(("%s 09:04:00.000,2222,09:04:00,10,100,BUY,9,10,5,\n" % DAY) * 3000)
            st = {}
            first = bl.build(d, now=datetime(2026, 11, 2, 9, 5, tzinfo=JST), state=st)
            self.assertEqual(first["stocks"], [])                # board not read yet
            for _ in range(10):
                v = bl.build(d, now=datetime(2026, 11, 2, 9, 5, tzinfo=JST), state=st)
            self.assertEqual(len(dict(v["stocks"][0]["ratio_hist"])), 4)
        finally:
            bl.MAX_READ_BYTES = old


class Wiring(unittest.TestCase):
    def test_observer_gateway_and_panel(self):
        import scripts.ai_brain_observer as obs
        name, pin = obs.BOARD_MODULE
        self.assertEqual(obs.git_blob_sha1((ROOT / "scripts" / (name + ".py")).read_bytes()), pin)
        src = (ROOT / "scripts" / "ai_brain_observer.py").read_text(encoding="utf-8")
        self.assertIn("board_live_pass(board_state, live)", src)
        gw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/scalp8_board.json') {", gw)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-scalp8-board-v1'", gw)
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        block = html.split("// OWNER 2026-11-02 「SCALP8の8銘柄の板パネルを、トレード中タブに作って。", 1)[1].split("})();", 1)[0]
        self.assertIn('fetch("/scalp8_board.json?t="+Date.now(),{cache:"no-store"})', block)
        self.assertIn('v.real_submit_allowed===false&&v.trade_instruction===false', block)
        for text in ("未検証の表示", 'b.textContent="板"', "--b8ask:#E0566B", "--b8bid:#3DBE7A", "OVER", "UNDERの割合", "a>=10"):
            self.assertIn(text, block)
        for banned in ("cockpitSpeak", "speechSynthesis", "RssOrder", "renderAttention", "order("):
            self.assertNotIn(banned, block)

    def test_observer_pass_prints_only_on_change(self):
        import contextlib
        import io
        import scripts.ai_brain_observer as obs
        d = tempfile.mkdtemp()
        write_day(d)
        st, out = {}, io.StringIO()
        with contextlib.redirect_stdout(out):
            for _ in range(3):
                r = obs.board_live_pass(st, Path(d) / "live.json", now=datetime(2026, 11, 2, 9, 5, tzinfo=JST))
        self.assertEqual(r, {"board_live": "BUILT", "stocks": 1, "real_submit_allowed": False})
        self.assertEqual(len(out.getvalue().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
