"""Backtest expected value of the cockpit's recorded signals and its REALTIME 5 ranking.

Synthetic records only (signals + MS2 ticks written here). Covers the replay
rules (fill window, target, stop, 15:20 exit, not filled, invalid), net and
gross statistics, past days only, the Brain observer's daily rebuild with a
pinned module, the Gateway route and the BRAIN-free UI hooks. No orders.
"""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts import v10_signal_ev_table as ev

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"
HTML = (ROOT / "index.html").read_text(encoding="utf-8").replace("\r\n", "\n")
NOW = datetime(2026, 10, 22, 7, 0, tzinfo=timezone.utc)  # 16:00 JST on 10/22


def write_day(records: Path, day: str, signals: list, ticks: list):
    d = records / day
    d.mkdir(parents=True)
    head = "captured_at,ticker,name,signal,strategy,signal_bar,entry,stop,target1,target2,market_state,breadth_pct,sector_breadth_pct,hold_signal,hold_score\n"
    (d / "trade_signals.csv").write_text(head + "".join(
        '"%s %s","%s","n","%s","%s","b","%s","%s","%s","0","",,,"",""\n' % (day, t, tk, sig, strat, e, st, tg)
        for t, tk, sig, strat, e, st, tg in signals), encoding="utf-8-sig")
    (d / "ticks.csv").write_text("captured_at,ticker,name,exchange_time,price,direction_estimate,bid,ask,note\n" + "".join(
        '"%s %s","%s","n","%s","%s","U","","",""\n' % (day, t, tk, t, p) for tk, t, p in ticks), encoding="utf-8-sig")


class Replay(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="v10-ev-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.records = Path(tmp) / "records"

    def test_target_stop_time_exit_not_filled_and_invalid(self):
        buy, short = "買いサイン", "空売りサイン"
        write_day(self.records, "2026-10-20", [
            ("09:20:00", "A.T", buy, "OR15押し目", 1000, 990, 1010),     # fills, hits target
            ("09:20:00", "B.T", short, "OR15戻り", 1000, 1010, 990),     # fills, hits stop
            ("09:20:00", "C.T", buy, "OR15押し目", 1000, 990, 1010),     # fills, exits 15:20
            ("09:20:00", "D.T", buy, "OR15押し目", 1000, 990, 1010),     # never reaches entry in 30 min
            ("09:20:00", "E.T", buy, "OR15押し目", 1000, 1010, 990),     # stop above entry: invalid
        ], [
            ("A.T", "09:21:00", 1000), ("A.T", "09:30:00", 1010),
            ("B.T", "09:21:00", 1000), ("B.T", "09:40:00", 1010),
            ("C.T", "09:21:00", 1001), ("C.T", "15:19:00", 1005), ("C.T", "15:25:00", 980),
            ("D.T", "09:21:00", 995), ("D.T", "10:00:00", 1001),
        ])
        table = ev.build(self.records, now=NOW)
        self.assertEqual(table["counts"], {"signals": 5, "filled": 3, "not_filled": 1, "invalid": 1, "overlapping_skipped": 0})
        buy_stats = table["by_strategy"]["OR15押し目|買いサイン"]
        self.assertEqual(buy_stats["n"], 2)
        self.assertEqual(buy_stats["exits"], {"TARGET": 1, "TIME_EXIT": 1})
        c_gross = (1005 / 1001 - 1) * 100   # C fills at the 1001 tick, not at the 1000 entry
        self.assertAlmostEqual(buy_stats["gross_ev_pct"], (1.0 + c_gross) / 2, places=3)
        # 楽天ゼロコース: no commission; 制度信用 buyer interest 2.80 %/year for one day
        self.assertAlmostEqual(buy_stats["ev_pct"], (1.0 + c_gross) / 2 - 2.80 / 365, places=3)
        self.assertAlmostEqual(buy_stats["breakeven_slippage_pct_per_side"], ((1.0 + c_gross) / 2 - 2.80 / 365) / 2, places=3)
        self.assertEqual(buy_stats["status"], "INSUFFICIENT")
        short_stats = table["by_strategy"]["OR15戻り|空売りサイン"]
        self.assertEqual(short_stats["exits"], {"STOP": 1})
        self.assertAlmostEqual(short_stats["gross_ev_pct"], -1.0, places=3)
        self.assertAlmostEqual(short_stats["ev_pct"], -1.0 - 1.10 / 365, places=3)  # 貸株料 1.10 %/year, one day
        self.assertEqual(table["assumptions"]["commission_pct_per_side"], 0.0)
        self.assertIs(table["real_submit_allowed"], False)
        self.assertIs(table["trade_instruction"], False)

    def test_only_completed_past_days_and_min_n(self):
        sigs = [("09:10:00", "T%d.T" % i, "買いサイン", "OR15押し目", 1000, 990, 1010) for i in range(25)]
        ticks = [("T%d.T" % i, "09:10:30", 1000) for i in range(25)] + [("T%d.T" % i, "09:59:00", 1010) for i in range(25)]
        write_day(self.records, "2026-10-21", sigs, ticks)
        write_day(self.records, "2026-10-22", sigs, ticks)
        morning = datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc)   # 10:00 JST: today's session not complete
        self.assertEqual(ev.build(self.records, now=morning)["days"], ["2026-10-21"])
        table = ev.build(self.records, now=NOW)                        # 16:00 JST: today is complete
        self.assertEqual(table["days"], ["2026-10-21", "2026-10-22"])
        table = ev.build(self.records, now=NOW, days=["2026-10-21"])
        stats = table["by_strategy"]["OR15押し目|買いサイン"]
        self.assertEqual((stats["n"], stats["status"]), (25, "OK"))

    def test_gaps_same_second_bar_close_and_overlap(self):
        buy, short = "買いサイン", "空売りサイン"
        write_day(self.records, "2026-10-21", [
            ("09:20:00", "G.T", buy, "S", 100, 99, 105),      # gap fill at 103, gap stop at 95
            ("09:20:00", "H.T", short, "S", 100, 101, 95),    # one second touches target and stop: stop
            ("09:20:30", "I.T", buy, "S", 100, 99, 105),      # bar 09:20 -> a 09:20:40 tick is inside the bar
            ("09:20:00", "J.T", buy, "S", 100, 99, 105),      # first trade of J
            ("09:30:00", "J.T", buy, "S", 100, 99, 105),      # J still open: skipped
        ], [
            ("G.T", "09:21:00", 103), ("G.T", "09:40:00", 95),
            ("H.T", "09:21:00", 100), ("H.T", "09:41:00", 94), ("H.T", "09:41:00", 102),
            ("I.T", "09:20:40", 100), ("I.T", "09:21:10", 99.5),
            ("J.T", "09:21:00", 100), ("J.T", "10:00:00", 105),
        ])
        # signal_bar column: write_day puts "b"; give I a real bar to test the bar-close rule
        path = self.records / "2026-10-21" / "trade_signals.csv"
        text = path.read_text("utf-8-sig").replace('"I.T","n","買いサイン","S","b"', '"I.T","n","買いサイン","S","2026-10-21 09:20"')
        path.write_text(text, encoding="utf-8-sig")
        import csv as _csv, io as _io
        rows = list(_csv.DictReader(_io.StringIO(text)))
        ticks = ev.load_ticks(self.records / "2026-10-21" / "ticks.csv")
        g = ev.replay(rows[0], ticks["G.T"])
        self.assertEqual((g["fill_price"], g["exit_price"], g["exit"]), (103, 95, "STOP"))
        h = ev.replay(rows[1], ticks["H.T"])
        self.assertEqual((h["exit"], h["exit_price"]), ("STOP", 102))
        i = ev.replay(rows[2], ticks["I.T"])
        self.assertEqual(i["state"], "NOT_FILLED")   # 09:20:40 is inside the 09:20 bar; 09:21:10 is below entry
        table = ev.build(self.records, now=NOW)
        self.assertEqual(table["counts"]["overlapping_skipped"], 1)

    def test_write_table_is_atomic_json(self):
        write_day(self.records, "2026-10-21", [], [("A.T", "09:00:00", 1)])
        out = self.records.parent / "signal_ev_table_v1.json"
        ev.write_table(self.records, out, now=NOW)
        self.assertEqual(json.loads(out.read_text("utf-8"))["schema_version"], ev.SCHEMA)
        self.assertFalse(out.with_name(out.name + ".tmp").exists())


class RuleShadow(unittest.TestCase):
    """OWNER 2026-10-21 「①②でSHADOW開始」: forward virtual trades from 2026-10-22 only."""

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="v10-rules-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.records = Path(tmp) / "records"

    def test_rule_widths_hold_and_forward_window(self):
        buy, short = "買いサイン", "空売りサイン"
        sigs = [
            ("09:20:00", "A.T", buy, "OR15押し目", 1000, 990, 1010),    # R1: target 1020 / stop 980
            ("10:30:00", "B.T", buy, "OR15押し目", 1000, 990, 1010),    # outside 9:15-10:00: no rule
            ("09:30:00", "C.T", short, "OR15戻り", 1000, 1010, 990),    # R2 needs a weak market
        ]
        ticks = [("A.T", "09:21:00", 1000), ("A.T", "09:40:00", 1012), ("A.T", "09:50:00", 1021),
                 ("B.T", "10:31:00", 1000), ("B.T", "10:40:00", 1011),
                 ("C.T", "09:31:00", 1000), ("C.T", "09:40:00", 985), ("C.T", "10:35:00", 975)]
        write_day(self.records, "2026-10-21", sigs, ticks)   # before the forward window
        write_day(self.records, "2026-10-22", sigs, ticks)
        path = self.records / "2026-10-22" / "trade_signals.csv"
        path.write_text(path.read_text("utf-8-sig").replace('"C.T","n","空売りサイン","OR15戻り","b","1000","1010","990","0",""',
                                                             '"C.T","n","空売りサイン","OR15戻り","b","1000","1010","990","0","地合い弱い"'),
                        encoding="utf-8-sig")
        view = ev.build_rule_shadow(self.records, now=NOW)
        self.assertEqual(view["days"], ["2026-10-22"])
        r1, r2 = view["forward"]["R1"], view["forward"]["R2"]
        self.assertEqual(r1["n"], 1)
        self.assertEqual(r1["recent"][0]["exit"], "TARGET")           # 1012 did not reach the widened 1020
        self.assertEqual(r1["recent"][0]["exit_price"], 1021)
        self.assertEqual(r2["n"], 1)
        # short: target 1000 - 3*10 = 970 not reached in 60 min; exits at the last tick by 10:31
        self.assertEqual((r2["recent"][0]["exit"], r2["recent"][0]["exit_price"]), ("TIME_EXIT", 985))
        self.assertIs(view["real_submit_allowed"], False)

    def test_gap_rules_follow_and_fade_from_the_open_to_ten(self):
        write_day(self.records, "2026-10-21", [], [("G.T", "15:00:00", 1000), ("H.T", "15:00:00", 1000), ("I.T", "15:00:00", 1000)])
        write_day(self.records, "2026-10-22", [], [
            ("G.T", "09:00:05", 1020), ("G.T", "09:59:00", 1030), ("G.T", "10:30:00", 900),   # +2 % gap, up to 10:00
            ("H.T", "09:00:05", 1005),                                                       # gap below 1 %: skipped
            ("I.T", "10:05:00", 1050),                                                       # first trade after 10:00: not entered
        ])
        view = ev.build_rule_shadow(self.records, now=NOW)
        a, b = view["forward"]["R3A_1000"], view["forward"]["R3B_1000"]
        self.assertEqual((a["n"], b["n"]), (1, 1))
        gross = (1030 / 1020 - 1) * 100
        self.assertAlmostEqual(a["recent"][0]["return_pct"], gross - 2.80 / 365, places=6)   # follow = long
        self.assertAlmostEqual(b["recent"][0]["return_pct"], -gross - 1.10 / 365, places=6)  # fade = short
        self.assertEqual(sorted(view["gap_rules"]), ["R3A_0915", "R3A_0930", "R3A_1000", "R3B_0915", "R3B_0930", "R3B_1000"])
        self.assertEqual(view["forward"]["R3A_0915"]["n"], 1)   # 09:00:05 fill, exit at the same tick by 09:15
        self.assertAlmostEqual(view["forward"]["R3A_0915"]["recent"][0]["return_pct"], -2.80 / 365, places=6)

    def test_gap_uses_the_reference_price_and_skips_splits(self):
        write_day(self.records, "2026-10-21", [], [("G.T", "15:24:00", 1000), ("S.T", "15:24:00", 5000)])
        write_day(self.records, "2026-10-22", [], [("G.T", "09:00:05", 1015), ("G.T", "09:59:00", 1030),
                                                   ("S.T", "09:00:05", 1010), ("S.T", "09:59:00", 1020)])
        (self.records / "2026-10-22" / "preopen.csv").write_text(
            "captured_at,ticker,name,reference_price\n"
            '"2026-10-22 08:59:50","G.T","n","1020"\n'      # official close 1020: the open 1015 is a -0.5 % gap
            '"2026-10-22 09:00:10","G.T","n","990"\n',      # after 09:00: ignored
            encoding="utf-8-sig")
        view = ev.build_rule_shadow(self.records, now=NOW)
        self.assertEqual(view["forward"]["R3A_1000"]["n"], 0)   # G.T: below 1 % with the reference; S.T: -80 % is a split

    def test_default_replay_is_unchanged(self):
        sig = {"signal": "買いサイン", "entry": "1000", "stop": "990", "target1": "1010", "captured_at": "2026-10-22 09:20:00", "signal_bar": "b"}
        ticks = [("09:21:00", 0, 1000), ("09:30:00", 1, 1010)]
        self.assertEqual(ev.replay(sig, ticks)["exit"], "TARGET")
        self.assertEqual(ev.replay(sig, ticks, target_mult=2, stop_mult=2)["exit"], "TIME_EXIT")

    def test_ui_marks_rule_matches(self):
        self.assertIn("const ruleFor=(x,nowMs)=>{", HTML)
        self.assertIn("に該当</b>（Shadow）", HTML)
        text = GATEWAY.read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/rule_shadow.json') {", text)


class ObserverDailyRebuild(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("obs_ev_under_test", ROOT / "scripts" / "ai_brain_observer.py")
        self.obs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.obs)
        tmp = tempfile.mkdtemp(prefix="v10-obs-ev-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.runtime = Path(tmp) / "100億PROJECT" / "files"
        write_day(self.runtime / "records", "2026-10-21", [], [("A.T", "09:00:00", 1)])
        self.live = self.runtime / "live_ms2.json"

    def test_pin_matches_the_committed_module(self):
        name, pin = self.obs.SIGNAL_EV_MODULE
        self.assertEqual(self.obs.git_blob_sha1((ROOT / "scripts" / (name + ".py")).read_bytes()), pin)

    def test_builds_when_missing_then_once_per_day_after_the_close(self):
        state = {}
        morning = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)  # 09:00 JST
        self.assertEqual(self.obs.signal_ev_pass(state, self.live, now=morning)["signal_ev"], "BUILT")
        self.assertIsNone(self.obs.signal_ev_pass(state, self.live, now=morning + timedelta(minutes=20)))
        after_close = datetime(2026, 10, 22, 6, 40, tzinfo=timezone.utc)  # 15:40 JST
        self.assertEqual(self.obs.signal_ev_pass(state, self.live, now=after_close)["signal_ev"], "BUILT")
        self.assertIsNone(self.obs.signal_ev_pass(state, self.live, now=after_close + timedelta(minutes=20)))

    def test_a_table_from_an_earlier_day_is_rebuilt_at_the_morning_start(self):
        evening = datetime(2026, 10, 21, 6, 0, tzinfo=timezone.utc)   # 15:00 JST: built, before the close rebuild
        self.assertEqual(self.obs.signal_ev_pass({}, self.live, now=evening)["signal_ev"], "BUILT")
        next_morning = datetime(2026, 10, 21, 23, 30, tzinfo=timezone.utc)  # 08:30 JST next day, fresh process
        self.assertEqual(self.obs.signal_ev_pass({}, self.live, now=next_morning)["signal_ev"], "BUILT")
        self.assertIsNone(self.obs.signal_ev_pass({}, self.live, now=next_morning + timedelta(hours=1)))

    def test_modified_module_is_refused_and_never_raises(self):
        scripts = Path(tempfile.mkdtemp(prefix="v10-obs-ev-mod-"))
        self.addCleanup(shutil.rmtree, scripts, True)
        (scripts / "v10_signal_ev_table.py").write_text("raise SystemExit('tampered')\n", encoding="utf-8")
        got = self.obs.signal_ev_pass({}, self.live, now=NOW, script_dir=scripts)
        self.assertEqual(got["signal_ev"], "BLOCKED")
        self.assertTrue(got["reason"].startswith("PINNED_MODULE_MISMATCH"))
        self.assertFalse((self.runtime / "signal_ev_table_v1.json").exists())


HARNESS = r"""
param([string]$Gateway, [string]$Dir)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Gateway,[ref]$t,[ref]$e)
$fn=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-SignalEvView'},$true))
. ([scriptblock]::Create($fn[0].Extent.Text))
$out=[ordered]@{}
foreach ($c in Get-ChildItem -LiteralPath $Dir -Directory) { $out[$c.Name] = (Get-SignalEvView $c.FullName).status }
$out.relative = (Get-SignalEvView 'relative').status
$out | ConvertTo-Json -Compress
"""


class GatewayRoute(unittest.TestCase):
    def test_route_is_wired(self):
        text = GATEWAY.read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/signal_ev.json') {", text)
        self.assertIn("$evView = Get-SignalEvView $RuntimeDir", text)

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell 5.1 required")
    def test_states(self):
        good = json.dumps({"schema_version": ev.SCHEMA, "real_submit_allowed": False, "trade_instruction": False})
        cases = {"valid": good, "missing": None, "unsafe": good.replace('"trade_instruction": false', '"trade_instruction": true'),
                 "broken": "{x"}
        with tempfile.TemporaryDirectory() as d:
            for name, text in cases.items():
                (Path(d) / name).mkdir()
                if text is not None:
                    (Path(d) / name / "signal_ev_table_v1.json").write_text(text, encoding="utf-8")
            h = Path(d) / "h.ps1"
            h.write_text(HARNESS, encoding="utf-8-sig")
            p = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(h), "-Gateway",
                                str(GATEWAY), "-Dir", d], capture_output=True, text=True, encoding="utf-8", errors="replace")
        got = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(got, {"broken": "503 Service Unavailable", "missing": "503 Service Unavailable",
                               "unsafe": "503 Service Unavailable", "valid": "200 OK", "relative": "503 Service Unavailable"})


class RealtimePanel(unittest.TestCase):
    def test_panel_is_in_realtime_5_and_needs_live(self):
        self.assertIn('evPanel.id="signal-ev-ranking";', HTML)
        self.assertIn('if(panes["ms2-live"]){const intro=panes["ms2-live"].querySelector(":scope > .pane-intro");', HTML)
        self.assertIn("const live=window.cockpitMs2ScreenReady?.(d)===true;", HTML)
        self.assertIn("発注はしません", HTML)

    @unittest.skipUnless(shutil.which("node"), "node not installed; the CI job runs it")
    def test_ranking_helpers_in_node(self):
        p = subprocess.run(["node", "--test", str(ROOT / "tests" / "v10_signal_ev_ranking.test.mjs")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout[-6000:] + "\n" + p.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
