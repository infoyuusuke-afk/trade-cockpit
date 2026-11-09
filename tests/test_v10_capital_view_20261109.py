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

    def test_held_rows_say_name_side_shares_and_amount(self):
        # OWNER 2026-11-09 「その場合のポジションはわかりやすく表示して」
        tr = pos.trades_of([day_trade("A.T", 1000, "09:30")], [], [], "2026-11-09", {"A.T": tk(("09:30:00", 1000), ("09:40:00", 1010))}, "09:45")
        h = pos.size(tr, 3_000_000, "09:45")["held"][0]
        self.assertEqual((h["name"], h["side"], h["shares"], h["amount"], h["open_yen"]), ("A.T", "買い", 3000, 3_000_000, 30000))
        self.assertIn("資金別の保有中の建玉（仮想・フルレバ）", HTML)
        for x in ("使っている枠 <b>", "全体の枠 ", 'class="cap-bar"', "入れなかったサイン（直近", '"持ち越し":"デイ"', "const caps=S.filter(s=>s.capital);"):
            self.assertIn(x, HTML)

    def test_priority_by_rule_and_reserve_for_positive_rules(self):
        # OWNER 2026-11-09 「枠が足りない時に期待値の高いルールを優先…後のサインを知っているように選ばない…マイナスのルールは
        # 入った後に1回分の枠が残る時だけ入る…持ち越しも同じ。先着順の数字も参考に残す」
        def dt(t, rule, at):
            return dict(day_trade(t, 1000, at), rule=rule)
        ev = {"R2": 0.3, "R4": -0.08}
        # same minute: R4 listed first, R2 is taken first; later signals are not looked at
        trs = pos.trades_of([dt("A.T", "R4", "09:30"), dt("B.T", "R2", "09:30"), dt("C.T", "R4", "09:30"), dt("D.T", "R2", "09:31")],
                            [], [], "2026-11-09", {}, "10:00")
        s = pos.size(trs, 3_000_000, "10:00", ev)
        got = [(x["ticker"], x["in"]) for x in s["_taken"]]
        # limit 9.9M: B(R2) 3M, then A(R4) needs 3M + one more 3M reserve -> 9M fits, C(R4) would leave 0.9M < 3M -> skipped,
        # D(R2) at 09:31 fits (9M)
        self.assertEqual(got, [("B.T", "09:30"), ("A.T", "09:30"), ("D.T", "09:31")])
        self.assertEqual(s["skipped_recent"][0]["reason"], "成績がマイナスの手法なので、最後の1回分の枠を残した")
        f = pos.size(trs, 3_000_000, "10:00")   # first come: A, B, C fill the room, D is skipped
        self.assertEqual([x["ticker"] for x in f["_taken"]], ["A.T", "B.T", "C.T"])
        # unknown rule = not positive; overnight holds follow their own figure
        carry = [{"ticker": "E.T", "side": "LONG", "decided_at": "2026-11-06 15:25:04", "reference_price": "1000"}]
        trs2 = pos.trades_of([], carry, [], "2026-11-09", {}, "10:00")
        self.assertEqual(trs2[0]["rule"], "ON_LONG")
        self.assertEqual(len(pos.size(trs2, 3_000_000, "10:00", {"ON_LONG": -0.1})["_taken"]), 1)   # 3M + 3M reserve <= 9.9M

    def test_rule_ev_fixed_from_days_before_today(self):
        with tempfile.TemporaryDirectory() as d:
            rt = Path(d)
            (rt / "records" / "2026-11-09").mkdir(parents=True)
            (rt / "rule_shadow_v1.json").write_text(json.dumps({"real_submit_allowed": False, "days": ["2026-11-06"],
                "forward": {"R2": {"ev_pct": 0.35, "n": 119}, "R4": {"ev_pct": -0.083, "n": 236}, "BRAIN": {"ev_pct": 1}}}), encoding="utf-8")
            (rt / pos.HISTORY_FILE).write_text("decision_date,side,status,evaluation_date,return_close_pct\n"
                                               "2026-11-05,LONG,検証済み,2026-11-06,1.0\n2026-11-06,LONG,検証済み,2026-11-09,-5.0\n", encoding="utf-8")
            e = pos.rule_ev(rt, rt / "records" / "2026-11-09", "2026-11-09")
            self.assertEqual(e["ev"]["R2"], 0.35)
            # OWNER 2026-11-09 「手法A〜D・ブレイン…を並べる」: the Brain's figure is kept for the chart only; no sized trade has rule BRAIN
            self.assertEqual(e["ev"]["BRAIN"], 1.0)
            self.assertFalse(any(t.get("rule") == "BRAIN" for t in pos.trades_of([dict(day_trade("A.T", 1000, "09:30"), rule="R4")], [], [], "2026-11-09", {}, "10:00")))
            self.assertAlmostEqual(e["ev"]["ON_LONG"], round(1.0 - pos.ON_RATE_DAY["ON_LONG"], 4))   # today's evaluation is not used
            # a later rebuild that includes today does not change today's figures
            (rt / "rule_shadow_v1.json").write_text(json.dumps({"real_submit_allowed": False, "days": ["2026-11-09"],
                "forward": {"R2": {"ev_pct": -9, "n": 1}}}), encoding="utf-8")
            self.assertEqual(pos.rule_ev(rt, rt / "records" / "2026-11-09", "2026-11-09")["ev"]["R2"], 0.35)
        self.assertIn('row("先着順なら（参考）"', HTML)
        self.assertIn("優先に使った手法の成績（前の日まで・1回の平均・費用込み）", HTML)

    def test_method_compare_chart(self):
        # OWNER 2026-11-09 「手法の勝率など結果については、グラフで比較、一目でわかる形にしてほしい」
        # OWNER 2026-11-09 「注文タブの資金別の下に『手法の成績』…ブレイン…通算損益の線グラフ。今日と通算をボタンで切り替え」
        for x in ("function renderMethods()", "手法の成績（メル・仮想）", "勝率（線＝50%）", "1回の平均（中央＝0）", "PF（線＝1.0）", "cap.methods_today",
                  'document.getElementById("cap-compare")', 'data-mview="today"', 'data-mview="total"', '["BRAIN","ブレイン"', "lineChart(series)", "cap.method_days"):
            self.assertIn(x, HTML)
        with tempfile.TemporaryDirectory() as d:
            rec = Path(d) / "records"
            (rec / "2026-11-09").mkdir(parents=True)
            tr = pos.trades_of([dict(day_trade("A.T", 1000, "09:30", "10:00", 1.0), rule="R4"),
                                dict(day_trade("B.T", 1000, "09:31", "10:00", -1.0), rule="R4")], [], [], "2026-11-09", {}, "15:30")
            v = pos.capital_view(rec, rec / "2026-11-09", "2026-11-09", "15:30", tr)
            self.assertEqual({k: v["methods_today"]["R4"][k] for k in ("n", "closed", "wins", "yen", "win", "pf")},
                             {"n": 2, "closed": 2, "wins": 1, "yen": 0, "win": 50.0, "pf": 1.0})
            self.assertEqual(v["method_days"], {})

    def test_100_share_column_shows_the_money_needed(self):
        # OWNER 2026-11-09 「ここに１００株（資金額）がでるとわかりやすい」
        self.assertIn("必要な資金 '+man(s.peak_amount)+'（今日いちばん多く持った額）", HTML)
        self.assertIn('row("今日いちばん多く持った額"', HTML)
        tr = pos.trades_of([day_trade("A.T", 1000, "09:30", "10:00", 1.0), day_trade("B.T", 2000, "09:40", "10:30", 1.0)], [], [], "2026-11-09", {}, "15:30")
        self.assertEqual(pos.size(tr, None, "15:30")["peak_amount"], 300_000)

    def test_skipped_signals_keep_the_reason(self):
        trades = [day_trade(f"{i}.T", 1000, "09:3%d" % i) for i in range(5)] + [day_trade("X.T", 40000, "09:40")]
        tr = pos.trades_of(trades, [], [], "2026-11-09", {}, "10:00")
        s = pos.size(tr, 3_000_000, "10:00")
        sk = s["skipped_recent"]
        self.assertEqual([x["reason"] for x in sk], ["1単元（100株）が資金より高い", "枠が足りない", "枠が足りない"])
        self.assertEqual(sk[1]["room"], 900_000)
        self.assertEqual(sk[0]["need"], 4_000_000)
        self.assertIn("'+heldBlock(S)+'", HTML)

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

    def test_sox_zone_label_in_the_margin(self):
        # OWNER 2026-11-09 「注意ゾーンの文字を帯の中から外し…右の外側に『注意 11,041〜11,724』…帯の色は…薄い黄色」
        self.assertIn('"rgba(255,217,87,.09)"', HTML)
        self.assertIn("'<text x=\"'+(W-R+6)+'\" y=\"'+(zm+4)+'\" fill=\"#ffd957\" font-size=\"11\" font-weight=\"700\">注意 '+yen(z.from)+'〜'+yen(z.to)+'</text>'", HTML)
        self.assertNotIn("'<text x=\"'+(L+6)+'\" y=\"'+(y(z.from)-6)+'\"", HTML)
        self.assertIn("W=1040,H=380,L=64,R=118,", HTML)

    def test_pts_tab_moves_the_three_blocks(self):
        # OWNER 2026-11-09 「PTS専用のタブを作って…OVERNIGHT 5の隣…三つをそこへまとめて移す。各欄の上に…日付を大きく出す。中身と計算は変えない」
        self.assertIn(' <button class="cockpit-tab" data-tab="overnight">OVERNIGHT 5</button>\n <button class="cockpit-tab" data-tab="pts">PTS</button>', HTML)
        self.assertIn('"overnight","pts","ms2-live"', HTML)
        for x in ('document.getElementById("ms2-pts-cards")', 'document.getElementById("ms2-ir-pts-cards")', 'document.getElementById("pts-morning-pickup")',
                  'dateLine("pts-date-night"', 'dateLine("pts-date-ir"', 'dateLine("pts-date-pickup"', "v.pts_session_date", "t[0].pts_date",
                  "x&&x.pts_date", '.tab-pane[data-pane="pts"] .warning'):
            self.assertIn(x, HTML)
        # the ids the renderers write into are still in the page exactly once
        for x in ('id="ms2-pts-cards"', 'id="ms2-ir-pts-cards"', 'id="ms2-ir-pts-meta"', 'ptsPanel.id="pts-morning-pickup"'):
            self.assertEqual(HTML.count(x), 1, x)

    def test_ir_date_only_from_the_ir_rows(self):
        # audit 6734811954: no current time and no other block's date for the IR block
        i = HTML.index('setDate("pts-date-ir"')
        seg = HTML[i - 400:i + 200]
        self.assertNotIn("d.updated_at", seg)
        self.assertNotIn("t[0].pts_date", seg)
        self.assertIn('"いつの夜か未確認"', seg)

    def test_collector_ir_rows_carry_the_pts_date(self):
        # OWNER 2026-11-09 「IRの行にPTSの日付を足して」: the IR row takes the matched PTS row's pts_date (no other field changes)
        src = (ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
        i = src.index("$irPtsCandidates += [pscustomobject]@{")
        row = src[i:src.index(chr(10), i)]
        self.assertIn("judgement=$judgement;pts_date=$ptsMatch.pts_date}", row)

    def test_capital_table_held_line_charts_and_earnings_tag(self):
        for s in ('id="cap-compare"', "virt-held-line", "cap-journal", "chartSvg(s.day_curve", "chartSvg(s.overnight_curve",
                  'class="earn-tag"', "hold-earn-split", "window.cockpitEarningsSoon=soon"):
            self.assertIn(s.replace('id="cap-compare"', 'el.id="cap-compare"'), HTML)
        self.assertNotIn("submitOrder", HTML[HTML.index("資金別（仮想・メル）") - 6000:HTML.index("資金別（仮想・メル）") + 6000])


if __name__ == "__main__":
    unittest.main()
