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
        self.assertEqual(table["counts"], {"signals": 5, "filled": 3, "not_filled": 1, "invalid": 1})
        buy_stats = table["by_strategy"]["OR15押し目|買いサイン"]
        self.assertEqual(buy_stats["n"], 2)
        self.assertEqual(buy_stats["exits"], {"TARGET": 1, "TIME_EXIT": 1})
        self.assertAlmostEqual(buy_stats["gross_ev_pct"], (1.0 + 0.5) / 2, places=3)
        self.assertAlmostEqual(buy_stats["ev_pct"], (1.0 + 0.5) / 2 - 0.2, places=3)
        self.assertEqual(buy_stats["status"], "INSUFFICIENT")
        short_stats = table["by_strategy"]["OR15戻り|空売りサイン"]
        self.assertEqual(short_stats["exits"], {"STOP": 1})
        self.assertAlmostEqual(short_stats["gross_ev_pct"], -1.0, places=3)
        self.assertIs(table["real_submit_allowed"], False)
        self.assertIs(table["trade_instruction"], False)

    def test_only_completed_past_days_and_min_n(self):
        sigs = [("09:%02d:00" % (10 + i), "A.T", "買いサイン", "OR15押し目", 1000, 990, 1010) for i in range(25)]
        ticks = [("A.T", "09:%02d:30" % (10 + i), 1000) for i in range(25)] + [("A.T", "09:59:00", 1010)]
        write_day(self.records, "2026-10-21", sigs, ticks)
        write_day(self.records, "2026-10-22", sigs, ticks)   # today: not used
        table = ev.build(self.records, now=NOW)
        self.assertEqual(table["days"], ["2026-10-21"])
        stats = table["by_strategy"]["OR15押し目|買いサイン"]
        self.assertEqual((stats["n"], stats["status"]), (25, "OK"))

    def test_write_table_is_atomic_json(self):
        write_day(self.records, "2026-10-21", [], [("A.T", "09:00:00", 1)])
        out = self.records.parent / "signal_ev_table_v1.json"
        ev.write_table(self.records, out, now=NOW)
        self.assertEqual(json.loads(out.read_text("utf-8"))["schema_version"], ev.SCHEMA)
        self.assertFalse(out.with_name(out.name + ".tmp").exists())


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
