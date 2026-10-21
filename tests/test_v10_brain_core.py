"""Brain core: top live signals by expected value (synthetic live data only; no orders).

Covers the rule / EV-table estimates and their shrinkage, the short squeeze
exclusion, freshness gates, the pick log and its replay in the rule Shadow,
the pinned observer pass, the Gateway route and the panel hooks.
"""
from datetime import datetime, timedelta, timezone
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts import v10_brain_core as brain
from scripts import v10_signal_ev_table as ev

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"
HTML = (ROOT / "index.html").read_text(encoding="utf-8").replace("\r\n", "\n")
NOW = datetime(2026, 10, 22, 0, 30, tzinfo=timezone.utc)  # 09:30 JST


def target(ticker, signal="買いサイン", strategy="OR15", entry=1000, stop=990, t1=1010, ratio=3.0, fresh=True, market="地合い中立"):
    return {"ticker": ticker, "name": "名" + ticker, "signal": signal, "strategy": strategy, "signal_bar_time": "2026-10-22 09:29",
            "entry_price": entry, "stop_price": stop, "target1": t1, "credit_ratio": ratio, "aggregate_row_fresh": fresh,
            "market_state": market}


def live(rows, *, at="2026-10-22 09:29:55", valid=100, stale=False):
    return {"updated_at": at, "valid": valid, "stale": stale, "all_targets": rows}


SHADOW = {"schema_version": ev.RULES_SCHEMA, "real_submit_allowed": False, "forward_from": "2026-10-22",
          "rules": ev.RULES, "forward": {"R1": {"n": 0}}}
TABLE = {"schema_version": ev.SCHEMA, "real_submit_allowed": False, "days": ["d"] * 20,
         "by_strategy": {"OR15戻り|空売りサイン": {"n": 100, "ev_pct": 0.2, "status": "OK"},
                         "OR15|買いサイン": {"n": 400, "ev_pct": -0.05, "status": "OK"}},
         "by_strategy_ticker": {"OR15戻り|空売りサイン|B.T": {"n": 30, "ev_pct": 0.5, "status": "OK"},
                                "OR15戻り|空売りサイン|C.T": {"n": 5, "ev_pct": 3.0, "status": "INSUFFICIENT"}}}


class Pick(unittest.TestCase):
    def test_rule_match_scores_with_shrinkage_and_wider_levels(self):
        view = brain.pick(live([target("A.T")]), ev_table=TABLE, rule_shadow=SHADOW, now=NOW)
        self.assertEqual(view["state"], "PICK")
        p = view["picks"][0]
        n_eff = 0.5 * 54
        self.assertEqual((p["rule"], p["source"], p["n_eff"]), ("R1", "RULE", round(n_eff, 1)))
        self.assertAlmostEqual(p["score_pct"], round(0.096 * n_eff / (n_eff + 30), 4))
        self.assertEqual((p["target"], p["stop"]), (1020, 980))   # R1: 2x target, 2x stop
        self.assertFalse(view["real_submit_allowed"])
        self.assertFalse(view["trade_instruction"])

    def test_ticker_table_then_strategy_and_ordering(self):
        rows = [target("B.T", "空売りサイン", "OR15戻り", 1000, 1010, 990),
                target("C.T", "空売りサイン", "OR15戻り", 1000, 1010, 990),
                target("D.T")]
        now = NOW + timedelta(hours=2)  # 11:30 JST: no rule window
        view = brain.pick(live(rows, at="2026-10-22 11:29:55"), ev_table=TABLE, rule_shadow=SHADOW, now=now)
        self.assertEqual([p["ticker"] for p in view["picks"]], ["B.T", "C.T"])
        self.assertEqual([p["source"] for p in view["picks"]], ["TICKER", "STRATEGY"])   # C.T: thin ticker row ignored
        reasons = {e["ticker"]: e["reason"] for e in view["excluded"]}
        self.assertIn("基準", reasons["D.T"])   # negative EV is never picked

    def test_short_squeeze_and_freshness_gates(self):
        rows = [target("B.T", "空売りサイン", "OR15戻り", 1000, 1010, 990, ratio=0.8),
                target("E.T", fresh=False), target("F.T", entry=None), target("G.T", ratio=None)]
        view = brain.pick(live(rows), ev_table=TABLE, rule_shadow=SHADOW, now=NOW)
        reasons = {e["ticker"]: e["reason"] for e in view["excluded"]}
        self.assertIn("踏み上げ注意", reasons["B.T"])
        self.assertIn("鮮度", reasons["E.T"])
        self.assertIn("未確定", reasons["F.T"])
        self.assertEqual(view["picks"][0]["ticker"], "G.T")
        self.assertIn("信用倍率不明（空売り状況 未確認）", view["picks"][0]["flags"])

    def test_r4_r5_conditions_strategy_and_the_best_matching_rule(self):
        up = dict(target("K.T", strategy="OR15押し目", entry=1010, stop=1000, t1=1015), open_price=1000)   # +1 % from the open
        other = dict(target("L.T", strategy="OR5初動", entry=1010, stop=1000, t1=1015), open_price=1000)   # not 押し目
        down = dict(target("M.T", "空売りサイン", "OR15戻り", 975, 980, 970), open_price=980, reference_price=1000)
        split = dict(target("N.T", "空売りサイン", "OR15戻り", 975, 980, 970), open_price=200, reference_price=1000)
        hm = "09:30"
        rules = SHADOW["rules"]
        self.assertEqual([k for k, _ in brain.rules_for(rules, up, hm)], ["R1", "R4"])
        self.assertEqual([k for k, _ in brain.rules_for(rules, other, hm)], ["R1"])
        self.assertEqual([k for k, _ in brain.rules_for(rules, down, hm)], ["R5"])
        self.assertEqual(brain.rules_for(rules, split, hm), [])   # an -80 % "gap" is a split, not R5
        # R1's out-of-sample test block counts 0.5, the search-selected R4 only 0.1: R1 is used
        self.assertEqual(brain.estimate(up, ev_table=None, rule_shadow=SHADOW, hm=hm)["rule"], "R1")
        # with forward results R4 can take over
        fwd = dict(SHADOW, forward={"R1": {"n": 0}, "R4": {"n": 60, "ev_pct": 0.3}})
        got = brain.estimate(up, ev_table=None, rule_shadow=fwd, hm=hm)
        self.assertEqual((got["rule"], got["forward_n"]), ("R4", 60))
        view = brain.pick(live([down]), ev_table=None, rule_shadow=SHADOW, now=NOW)
        p = view["picks"][0]
        self.assertEqual((p["rule"], p["forward_n"], p["n_eff"]), ("R5", 0, round(0.1 * 44, 1)))
        self.assertEqual((p["target"], p["stop"]), (960, 985))

    def test_valid_is_the_collectors_integer_row_count(self):
        for valid, state in ((100, "PICK"), (95, "PICK"), (90, "PICK"), (89, "NOT_LIVE"), (111, "NOT_LIVE"),
                             (True, "NOT_LIVE"), ("100", "NOT_LIVE"), (None, "NOT_LIVE")):
            view = brain.pick(live([target("A.T")], valid=valid), ev_table=TABLE, rule_shadow=SHADOW, now=NOW)
            self.assertEqual(view["state"], state, valid)

    def test_not_live(self):
        for kw in ({"stale": True}, {"valid": False}, {"at": "2026-10-22 09:28:00"}, {"at": ""}):
            view = brain.pick(live([target("A.T")], **kw), ev_table=TABLE, rule_shadow=SHADOW, now=NOW)
            self.assertEqual((view["state"], view["picks"]), ("NOT_LIVE", []), kw)

    def test_at_most_three_and_one_per_stock(self):
        rows = [target(t) for t in ("A.T", "A.T", "H.T", "I.T", "J.T")]
        view = brain.pick(live(rows), ev_table=TABLE, rule_shadow=SHADOW, now=NOW)
        self.assertEqual([p["ticker"] for p in view["picks"]], ["A.T", "H.T", "I.T"])
        self.assertEqual([p["rank"] for p in view["picks"]], [1, 2, 3])


class LogAndShadow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v10-brain-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_picks_logged_once_and_replayed_with_the_rule(self):
        (self.tmp / "signal_ev_table_v1.json").write_text(json.dumps(TABLE), encoding="utf-8")
        (self.tmp / "rule_shadow_v1.json").write_text(json.dumps(SHADOW, ensure_ascii=False), encoding="utf-8")
        logged = set()
        first = brain.write_pick(self.tmp, live([target("A.T")]), now=NOW, logged=logged)
        again = brain.write_pick(self.tmp, live([target("A.T")], at="2026-10-22 09:30:01"), now=NOW + timedelta(seconds=6), logged=set())
        self.assertEqual((first["logged_new"], again["logged_new"]), (1, 0))   # dedupe survives a restart
        path = self.tmp / "records" / "2026-10-22" / brain.PICKS_FILE
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual((len(rows), rows[0]["rule"], float(rows[0]["stop"]), float(rows[0]["target1"])), (1, "R1", 990.0, 1010.0))
        self.assertEqual(json.loads((self.tmp / "brain_pick_v1.json").read_text("utf-8"))["state"], "PICK")
        # recorded ticks: fill at 1000 after the pick, R1's 2x target 1020 is reached before its 2x stop 980
        (path.parent / "ticks.csv").write_text("captured_at,ticker,name,exchange_time,price,direction_estimate,bid,ask,note\n" + "".join(
            '"x","A.T","n","%s","%s","U","","",""\n' % (t, p) for t, p in (("09:31:00", 1000), ("09:40:00", 985), ("09:50:00", 1021))),
            encoding="utf-8-sig")
        view = ev.build_rule_shadow(self.tmp / "records", now=datetime(2026, 10, 22, 7, 0, tzinfo=timezone.utc))
        b = view["forward"]["BRAIN"]
        self.assertEqual((b["n"], b["recent"][0]["exit"]), (1, "TARGET"))
        self.assertAlmostEqual(b["recent"][0]["return_pct"], 2.1 - 2.80 / 365, places=6)


class Observer(unittest.TestCase):
    def test_pinned_pass_writes_the_pick_and_prints_on_change_only(self):
        spec = importlib.util.spec_from_file_location("obs_brain_under_test", ROOT / "scripts" / "ai_brain_observer.py")
        obs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(obs)
        name, pin = obs.BRAIN_CORE_MODULE
        self.assertEqual(obs.git_blob_sha1((ROOT / "scripts" / (name + ".py")).read_bytes()), pin)
        tmp = Path(tempfile.mkdtemp(prefix="v10-obs-brain-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "live_ms2.json"
        path.write_text(json.dumps(live([target("A.T")]), ensure_ascii=False), encoding="utf-8")
        state = {}
        got = obs.brain_core_pass(state, path, now=NOW)
        self.assertEqual(got, {"brain_core": "NO_PICK", "picks": 0, "logged_new": 0, "real_submit_allowed": False})  # no tables yet
        self.assertEqual(obs.brain_core_pass(state, path, now=NOW)["brain_core"], "NO_PICK")
        path.write_text("{", encoding="utf-8")
        self.assertEqual(obs.brain_core_pass(state, path, now=NOW)["brain_core"], "BLOCKED")
        bad = {}
        bad_dir = tmp / "bad"
        bad_dir.mkdir()
        (bad_dir / (name + ".py")).write_text("x = 1\n", encoding="utf-8")
        got = obs.brain_core_pass(bad, path, now=NOW, script_dir=bad_dir)
        self.assertEqual(got["reason"], "PINNED_MODULE_MISMATCH:" + name)


class Wiring(unittest.TestCase):
    def test_gateway_route_and_panel(self):
        text = GATEWAY.read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/brain_pick.json') {", text)
        self.assertIn("'100b-v10-brain-pick-v1'", text)
        self.assertIn("'BRAIN_PICK_STALE'", text)
        self.assertIn('<div id="brain-pick-rows">', HTML)
        self.assertIn("window.cockpitMs2ScreenReady?.(d)!==true||!(age<=30)", HTML)
        self.assertIn("v.trade_instruction===false", HTML)
        self.assertIn("window.cockpitMs2RowReady?.(x)===true&&x.signal===p.signal&&x.strategy===p.strategy", HTML)
        self.assertIn("未検証：過去記録だけの数字（Shadow実績まだ0回）", HTML)
        self.assertIn("ブレインの選択（検証中・期待値は仮の数字・Shadow・発注しません）", HTML)
        self.assertIn("if(r.strategy&&r.strategy!==x?.strategy)continue;", HTML)
        self.assertIn("if(best&&best.score>=sc)continue;", HTML)

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell 5.1 required")
    def test_gateway_states(self):
        harness = r"""
param([string]$Gateway, [string]$Dir)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Gateway,[ref]$t,[ref]$e)
$fn=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-BrainPickView'},$true))
. ([scriptblock]::Create($fn[0].Extent.Text))
(Get-Item -LiteralPath (Join-Path $Dir 'old\brain_pick_v1.json')).LastWriteTimeUtc = [DateTime]::UtcNow.AddMinutes(-5)
$o=[ordered]@{}; foreach($c in Get-ChildItem -LiteralPath $Dir -Directory){ $o[$c.Name]=(Get-BrainPickView $c.FullName).status }
$o | ConvertTo-Json -Compress
"""
        good = json.dumps({"schema_version": brain.SCHEMA, "real_submit_allowed": False, "trade_instruction": False, "picks": []})
        with tempfile.TemporaryDirectory() as d:
            for name, text in {"valid": good, "missing": None, "old": good,
                               "unsafe": good.replace('"trade_instruction": false', '"trade_instruction": true')}.items():
                (Path(d) / name).mkdir()
                if text is not None:
                    (Path(d) / name / "brain_pick_v1.json").write_text(text, encoding="utf-8")
            h = Path(d) / "h.ps1"
            h.write_text(harness, encoding="utf-8-sig")
            p = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(h), "-Gateway", str(GATEWAY),
                                "-Dir", d], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(json.loads(p.stdout.strip().splitlines()[-1]),
                         {"missing": "503 Service Unavailable", "old": "503 Service Unavailable",
                          "unsafe": "503 Service Unavailable", "valid": "200 OK"})


if __name__ == "__main__":
    unittest.main()
