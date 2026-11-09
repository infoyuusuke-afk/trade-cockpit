"""OWNER 2026-11-09: 資金別の仮想（100株・300万・500万・信用）、1日の損益の線グラフ、決算またぎの印、ステータスランプ、PCの照合."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts import v10_positions_live as pos

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def tk(*rows):
    return [(t, i, p) for i, (t, p) in enumerate(rows)]


def day_trade(ticker, fill, t_in, t_out=None, ret=None, short=False):
    return {"status": "CLOSED" if t_out else "OPEN", "ticker": ticker, "name": ticker, "signal": "空売りサイン" if short else "買いサイン",
            "fill_price": fill, "fill_time": t_in + ":00", "exit_time": (t_out + ":00") if t_out else None, "return_pct": ret}


class Sizing(unittest.TestCase):
    def test_one_trade_buys_the_capital_floored_to_100_shares(self):
        tr = pos.trades_of([day_trade("A.T", 1000, "09:30", "10:00", 1.0)], [], [], "2026-11-09", {"A.T": tk(("09:30:00", 1000))}, "15:30")
        for label, capital, shares in (("100株", None, 100), ("300万", 3_000_000, 3000), ("500万", 5_000_000, 5000)):
            s = pos.size(tr, capital, "15:30")
            self.assertEqual(s["_taken"][0]["shares"], shares, label)
            self.assertEqual(s["rows"]["day"]["done"], round(0.01 * 1000 * shares))

    def test_margin_limit_skips_and_counts(self):
        trades = [day_trade(f"{i}.T", 1000, "09:30") for i in range(5)]
        tr = pos.trades_of(trades, [], [], "2026-11-09", {}, "10:00")
        s = pos.size(tr, 3_000_000, "10:00")   # 3 trades of 3,000,000 fit in 9,900,000; the 4th and 5th do not
        self.assertEqual(len(s["_taken"]), 3)
        self.assertEqual(s["skipped_room"], 2)
        self.assertEqual(pos.size(tr, None, "10:00")["skipped_room"], 0)   # 100 shares: no limit

    def test_expensive_stock_is_skipped_apart(self):
        tr = pos.trades_of([day_trade("X.T", 40000, "09:30")], [], [], "2026-11-09", {}, "10:00")
        s = pos.size(tr, 3_000_000, "10:00")
        self.assertEqual((s["skipped_price"], s["skipped_room"]), (1, 0))

    def test_overnight_uses_the_14_00_tick_when_the_file_is_missing_and_pays_interest(self):
        carry = [{"ticker": "B.T", "name": "B", "side": "LONG", "decided_at": "2026-11-06 15:25:04", "reference_price": "1000"}]
        ticks = {"B.T": tk(("09:00:01", 990), ("13:59:30", 1010), ("14:30:00", 1050))}
        tr = pos.trades_of([], carry, [], "2026-11-09", ticks, "15:30")
        self.assertEqual(tr[0]["exit"], 1010)
        s = pos.size(tr, None, "15:30")
        self.assertEqual(s["rows"]["overnight"]["done"], round(10 * 100 - 1000 * 100 * 0.028 * 3 / 365))
        curve = pos.curve(s["_taken"], ("overnight",), pos.marks(end="14:00"), "15:30")
        self.assertEqual(curve[0], ["09:00", 0, -1000])
        self.assertEqual(curve[-1][1], curve[-1][2])

    def test_today_15_25_picks_are_not_in_today(self):
        carry = [{"ticker": "C.T", "side": "LONG", "decided_at": "2026-11-09 15:25:04", "reference_price": "1000"}]
        self.assertEqual(pos.trades_of([], carry, [], "2026-11-09", {}, "15:40"), [])

    def test_curve_stops_at_now(self):
        tr = pos.trades_of([day_trade("A.T", 1000, "09:30")], [], [], "2026-11-09", {"A.T": tk(("09:30:00", 1000), ("09:40:00", 1010))}, "09:45")
        s = pos.size(tr, None, "09:45")
        c = pos.curve(s["_taken"], ("day",), pos.marks(), "09:45")
        self.assertEqual(c[-1], ["09:45", 0, 1000])
        self.assertEqual(len(c), 10)

    def test_view_keeps_the_day_and_adds_past_days(self):
        with tempfile.TemporaryDirectory() as d:
            rec = Path(d) / "records"
            (rec / "2026-11-06").mkdir(parents=True)
            (rec / "2026-11-09").mkdir(parents=True)
            (rec / "2026-11-06" / pos.DAY_FILE).write_text(json.dumps({"date": "2026-11-06", "sizes": {"300万": {"done": 1000, "closed": 2, "wins": 1}}}), encoding="utf-8")
            tr = pos.trades_of([day_trade("A.T", 1000, "09:30", "10:00", 1.0)], [], [], "2026-11-09", {}, "15:30")
            v = pos.capital_view(rec, rec / "2026-11-09", "2026-11-09", "15:30", tr)
            s = {x["label"]: x for x in v["sizes"]}
            self.assertEqual(s["300万"]["total_done"], 1000 + 30000)
            self.assertEqual(s["300万"]["total_pct"], round(31000 / 3_000_000 * 100, 2))
            self.assertIsNone(s["100株"]["total_pct"])
            self.assertEqual(v["from"], "2026-11-06")
            self.assertTrue((rec / "2026-11-09" / pos.DAY_FILE).is_file())
            self.assertFalse(v["real_submit_allowed"])


class EarningsMarks(unittest.TestCase):
    def write(self, d, dates, times=None, gen="2026-11-09T08:40:00+09:00"):
        Path(d, pos.EARN_FILE).write_text(json.dumps({"schema_version": "100b-v10-earnings-dates-pc-v1", "generated_at": gen,
                                                       "dates": dates, "times": times or {}}), encoding="utf-8")

    def test_tonight_tomorrow_unknown_and_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, {"1111": ["2026-11-09"], "2222": ["2026-11-09"], "3333": ["2026-11-10"], "4444": ["2026-11-10"],
                           "5555": ["2026-11-10"], "6666": ["2026-11-11"], "7777": ["2026-11-06"]},
                       {"1111": {"2026-11-09": "15:30"}, "2222": {"2026-11-09": "14:00"}, "3333": {"2026-11-10": "11:30"},
                        "4444": {"2026-11-10": "15:30"}})
            items = pos.earnings_soon(Path(d), "2026-11-09")["items"]
            self.assertEqual(items["1111"], {"label": "今夜決算", "date": "2026-11-09", "time": "15:30"})
            self.assertNotIn("2222", items)            # announced in today's session, before the 15:25 pick
            self.assertEqual(items["3333"]["label"], "明日決算")
            self.assertNotIn("4444", items)            # after the 14:00 exit
            self.assertEqual(items["5555"], {"label": "明日決算", "date": "2026-11-10", "time": ""})   # 時刻未確認
            self.assertNotIn("6666", items)
            self.assertNotIn("7777", items)

    def test_friday_reaches_monday_and_old_file_is_marked(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, {"1111": ["2026-11-09"]}, gen="2026-11-05T08:40:00+09:00")
            v = pos.earnings_soon(Path(d), "2026-11-06")
            self.assertEqual(v["items"]["1111"]["label"], "明日決算")
            self.assertEqual(v["state"], "OLD")

    def test_morning_shows_the_held_window_and_holidays_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, {"1111": ["2026-11-09"], "2222": ["2026-11-09"], "3333": ["2026-11-24"], "4444": ["2026-11-23"]},
                       {"2222": {"2026-11-09": "15:30"}})
            m = pos.earnings_soon(Path(d), "2026-11-09", "10:00")["items"]
            self.assertEqual(m, {"1111": {"label": "今日決算", "date": "2026-11-09", "time": ""}})   # 15:30 is after the 14:00 exit
            fri = pos.earnings_soon(Path(d), "2026-11-20", "15:30")["items"]
            self.assertEqual(fri["3333"]["label"], "明日決算")        # Monday 11/23 is a holiday: the next session is Tuesday
            self.assertEqual(fri["4444"]["label"], "休みの日に決算")

    def test_closed_trade_without_return_does_not_break_the_view(self):
        trades = [day_trade("A.T", 1000, "09:30", "10:00", None), day_trade("B.T", 1000, "09:31", "10:00", -5.0)]
        tr = pos.trades_of(trades, [], [], "2026-11-09", {}, "15:30")
        s = pos.size(tr, None, "15:30")
        self.assertEqual(s["limit_hit_at"], None)
        self.assertEqual(s["rows"]["day"]["closed"], 1)

    def test_no_file_means_no_marks(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(pos.earnings_soon(Path(d), "2026-11-09"), {"state": "NO_FILE", "items": {}})

    def test_split_counts_only_marked_days(self):
        with tempfile.TemporaryDirectory() as d:
            rt = Path(d)
            (rt / "records" / "2026-11-09").mkdir(parents=True)
            pos.keep_marks(rt / "records" / "2026-11-09", [{"ticker": "1111.T"}, {"ticker": "2222.T"}],
                           {"state": "OK", "items": {"1111": {"label": "今夜決算", "date": "2026-11-09", "time": ""}}})
            (rt / pos.HISTORY_FILE).write_text(
                "decision_date,ticker,status,return_close_pct\n2026-11-09,1111.T,検証済み,2.0\n2026-11-09,2222.T,検証済み,-1.0\n"
                "2026-11-06,3333.T,検証済み,5.0\n", encoding="utf-8")
            s = pos.earnings_split(rt)
            self.assertEqual(s["earnings"], {"n": 1, "win_pct": 100.0, "avg_pct": 2.0})
            self.assertEqual(s["other"], {"n": 1, "win_pct": 0.0, "avg_pct": -1.0})
            self.assertEqual(s["from"], "2026-11-09")


class Screen(unittest.TestCase):
    def test_lamp_follows_the_pc(self):
        self.assertIn('badge.textContent=live?"V10 / LIVE":phase==="down"?"V10 / 停止":"V10 / 時間外"', HTML)
        # audit 6734206848: the unified handler is the same one line as before; the lamp and the PC check are a separate listener
        line = HTML[HTML.index('document.addEventListener("ms2RssUpdate",e=>{const d=e.detail||{},live='):]
        line = line[:line.index("\n")]
        self.assertNotIn("cockpitLamp", line)
        self.assertNotIn("PCの照合", line)
        self.assertIn("window.cockpitLampState={live,phase,at:d.updated_at||\"\"};window.cockpitLampRefresh();", HTML)

    def test_yellow_when_public_analysis_is_old_and_tooltip_names_it(self):
        # OWNER 2026-11-09 「状態のランプに黄も入れて…マウスを乗せたら何が古いかを文字で出す」
        self.assertIn('badge.classList.add(live?(warn?"status-warn":"status-ok")', HTML)
        self.assertIn('"公開の分析データが古い：\\n"+f.lines.join("\\n")', HTML)
        self.assertIn("files.filter(([,x])=>x.stale||x.ok===false)", HTML)
        self.assertIn("setInterval(loadFeed,60000)", HTML)
        self.assertIn(".cockpit-brand small.status-ok{", HTML)
        self.assertIn("if(!window.cockpitLampSet){", HTML)

    def test_pc_check_replaces_the_cloud_line(self):
        self.assertIn('ver.textContent="PCの照合 "', HTML)
        self.assertIn('ver.classList.toggle("down",!live&&phase==="down");', HTML)

    def test_rule4_label_says_the_or15_high_pullback(self):
        # OWNER 2026-11-09 「④の画面の説明が中身（寄りから+0.5%以上で最初の15分の高値を抜く）と合っているか確かめ、違えば直す」
        from scripts import v10_signal_ev_table as ev
        r4 = ev.RULES["R4"]
        self.assertIn("寄りから+0.5%以上", r4["label"])
        self.assertIn("最初の15分の高値", r4["label"])
        self.assertEqual((r4["strategy"], r4["min_move_pct"], r4["side"], r4["target_mult"], r4["stop_mult"]), ("OR15押し目", 0.5, 1, 2.0, 2.0))
        self.assertNotIn('fetch("market_summary.json?t="+Date.now(),{cache:"no-store"}).then(r=>r.json()).catch(()=>null).then(s=>{', HTML)

    def test_capital_table_held_line_charts_and_earnings_tag(self):
        for s in ('id="cap-compare"', "virt-held-line", "cap-journal", "chartSvg(s.day_curve", "chartSvg(s.overnight_curve",
                  'class="earn-tag"', "hold-earn-split", "window.cockpitEarningsSoon=soon"):
            self.assertIn(s.replace('id="cap-compare"', 'el.id="cap-compare"'), HTML)
        self.assertNotIn("submitOrder", HTML[HTML.index("資金別（仮想・メル）") - 6000:HTML.index("資金別（仮想・メル）") + 6000])


if __name__ == "__main__":
    unittest.main()
