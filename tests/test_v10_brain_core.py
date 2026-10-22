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

    def test_rule_signals_list_every_rule_match_for_the_voice(self):
        rows = [target("A.T"),                                                     # R1 at 09:30
                target("D.T", strategy="OR15押し目"),                                # R1 as well
                target("B.T", "空売りサイン", "OR15戻り", 1000, 1010, 990),           # no rule: EV table only
                target("Q.T", "空売りサイン", "OR15戻り", 975, 980, 970, ratio=0.5)]  # squeeze risk: left out
        view = brain.pick(live(rows), ev_table=TABLE, rule_shadow=SHADOW, now=NOW)
        self.assertEqual([(x["ticker"], x["rule"]) for x in view["rule_signals"]], [("A.T", "R1"), ("D.T", "R1")])
        self.assertEqual((view["rule_signals"][0]["target"], view["rule_signals"][0]["stop"]), (1020, 980))
        self.assertEqual(brain.pick(live(rows, stale=True), ev_table=TABLE, rule_shadow=SHADOW, now=NOW)["rule_signals"], [])

    def test_specialist_attention_is_a_flag_and_a_list_not_a_score(self):
        rows = [target("A.T"), target("K.T", ratio=3.0)]
        att = {"A": [{"role": "pre_next", "report_id": "r.pre_next", "expires_at": "x"}],
               "K": [{"role": "supply_sq", "report_id": "r.supply_sq", "expires_at": "x"}]}
        plain = brain.pick(live(rows), ev_table=TABLE, rule_shadow=SHADOW, now=NOW)
        view = brain.pick(live(rows), ev_table=TABLE, rule_shadow=SHADOW, now=NOW, attention={"A.T".replace(".T", ""): att["A"]})
        a = next(p for p in view["picks"] if p["ticker"] == "A.T")
        self.assertIn("専門AIが先回り監視中（pre_next）", a["flags"])
        self.assertEqual([p["score_pct"] for p in view["picks"]], [p["score_pct"] for p in plain["picks"]])   # no score change
        self.assertEqual(view["specialist_watch"], [{"code": "A", "name": "名A.T", "roles": ["pre_next"], "signal_now": "買いサイン"}])

    def test_jpx_daily_margin_replaces_the_weekly_ratio(self):
        # synthetic cache (no real balances): code "B" is sale-heavy, "A" buy-heavy
        cache = {"schema_version": "100b-v10-jpx-margin-all-cache-v1", "as_of_date": "2026-10-20",
                 "issue_count": 4000, "dropped_blocks": 0,
                 "issues": {"B": {"sales": 2000, "purchases": 1000, "sales_change": 0, "purchases_change": 0},
                            "A": {"sales": 1000, "purchases": 4000, "sales_change": 0, "purchases_change": 0}},
                 "real_submit_allowed": False, "trade_instruction": False}
        rows = [target("B.T", "空売りサイン", "OR15戻り", 1000, 1010, 990, ratio=3.0), target("A.T", ratio=None)]
        later = NOW + timedelta(hours=2)
        view = brain.pick(live(rows, at="2026-10-22 11:29:55"), ev_table=TABLE, rule_shadow=SHADOW, now=later, margin=cache)
        reasons = {e["ticker"]: e["reason"] for e in view["excluded"]}
        self.assertIn("売り長（信用倍率0.50）", reasons["B.T"])          # weekly 3.0 replaced by the daily 0.50
        self.assertEqual(brain.margin_ratio(cache, "B.T", now=later), (0.5, "10/20"))
        a = next(x for x in view["excluded"] + view["picks"] if x["ticker"] == "A.T")
        self.assertNotIn("信用倍率不明", str(a))
        stale = dict(cache, as_of_date="2026-10-01")                      # older than 7 days: not used
        view = brain.pick(live(rows, at="2026-10-22 11:29:55"), ev_table=TABLE, rule_shadow=SHADOW, now=later, margin=stale)
        self.assertEqual([p["ticker"] for p in view["picks"]], ["B.T"])
        self.assertIsNone(brain.margin_ratio(dict(cache, schema_version="x"), "B.T", now=later))
        self.assertIsNone(brain.margin_ratio(dict(cache, issue_count=120), "B.T", now=later))          # partial cache
        self.assertIsNone(brain.margin_ratio(dict(cache, dropped_blocks=200), "B.T", now=later))       # > 1 % dropped
        zero = dict(cache, issues={"B": {"sales": 0, "purchases": 1000, "sales_change": 0, "purchases_change": 0}})
        self.assertEqual(brain.margin_ratio(zero, "B.T", now=later), (None, "10/20"))
        view = brain.pick(live(rows, at="2026-10-22 11:29:55"), ev_table=TABLE, rule_shadow=SHADOW, now=later, margin=zero)
        b = next(p for p in view["picks"] if p["ticker"] == "B.T")
        self.assertIn("JPX日次 10/20申込みは売0（倍率なし・週次の倍率を使用）", b["flags"])

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


    def test_attention_list_keeps_the_day_newest_first(self):
        # OWNER 2026-10-23 「注目」欄: new ranking entries and rule 1/2/4/5 signals, each logged once
        (self.tmp / "signal_ev_table_v1.json").write_text(json.dumps(TABLE), encoding="utf-8")
        (self.tmp / "rule_shadow_v1.json").write_text(json.dumps(SHADOW, ensure_ascii=False), encoding="utf-8")
        rows = [target("A.T"), target("D.T", strategy="OR15押し目")]
        first = brain.write_pick(self.tmp, live(rows), now=NOW, logged=set(), logged_rules=set())
        again = brain.write_pick(self.tmp, live(rows, at="2026-10-22 09:30:01"), now=NOW + timedelta(seconds=6),
                                 logged=set(), logged_rules=set())
        self.assertEqual((first["logged_rule_new"], again["logged_rule_new"]), (2, 0))   # dedupe survives a restart
        # the signal is gone later in the day: the list still keeps it
        later = brain.write_pick(self.tmp, live([], at="2026-10-22 11:00:00"), now=NOW + timedelta(hours=1, minutes=30),
                                 logged=set(), logged_rules=set())
        today = later["today"]
        self.assertEqual(today["date"], "2026-10-22")
        kinds = [(x["kind"], x["ticker"]) for x in today["attention"]]
        self.assertIn(("RULE", "A.T"), kinds)
        self.assertIn(("RULE", "D.T"), kinds)
        self.assertEqual(today["new_picks_total"], sum(k == "RANKING" for k, _ in kinds))
        self.assertGreaterEqual(today["new_picks_total"], 1)
        self.assertEqual(today["rule_signals_total"], 2)
        stamps = [x["captured_at"] for x in today["attention"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True))                               # newest first
        rule = next(x for x in today["attention"] if x["kind"] == "RULE")
        self.assertTrue(rule["label"].startswith("①"))
        ranking = next(x for x in today["attention"] if x["kind"] == "RANKING")
        self.assertTrue(ranking["label"].startswith("ブレインのランキング入り"))
        nextday = brain.write_pick(self.tmp, live([]), now=NOW + timedelta(days=1), logged=set(), logged_rules=set())
        self.assertEqual((nextday["today"]["date"], nextday["today"]["attention"]), ("2026-10-23", []))   # a new day starts empty
        # top of every tab: the box sits between the status bar and <main>
        self.assertIn('<b id="unified-mode-time">—</b></div></div><div class="unified-mode-wrap attention-wrap"><section id="attention-box"', HTML)
        self.assertIn("if(brainPick?.today?.date===jst)attentionToday=brainPick.today;", HTML)
        self.assertIn("検証中（Shadow）・実注文には使いません", HTML)

    def test_new_ranking_entry_voice_once_with_verifying(self):
        text = COLLECTOR.read_text(encoding="utf-8-sig")
        self.assertIn('("注目、検証中。ブレインのランキングに新しく入りました。"', text)
        self.assertIn('("注目、検証中。"+$ruleName+"に該当。"', text)
        self.assertIn("foreach ($x in (Get-BrainNewPicks $brainPickPath (Get-Date))) {", text)
        self.assertIn("if ($spokenNewPicks.ContainsKey($key)) { continue }", text)
        self.assertIn("$spokenRuleSignals=@{}; $spokenNewPicks=@{}; $preopenGapSpoken=$false", text)
        body = text[text.index("function Get-BrainNewPicks"):text.index("function Test-RuleSignalStillListed")]
        self.assertIn("[string]$view.state -cne 'PICK'", body)
        self.assertIn("Test-BrainPickFresh $view.generated_at $Now", body)


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


COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"


class CollectorVoice(unittest.TestCase):
    def test_signal_voice_is_rules_only_and_855_reads_gap_downs(self):
        text = COLLECTOR.read_text(encoding="utf-8-sig")
        self.assertNotIn("$voiceCandidates", text)                      # the voice for every lit signal is gone
        self.assertNotIn("キオクシア、8時55分判定", text)
        # audit 6326225807: the current clock, not the cycle start, is the freshness reference
        self.assertIn("foreach ($x in (Get-BrainRuleSignals $brainPickPath (Get-Date))) {", text)
        self.assertNotIn("Get-BrainRuleSignals $brainPickPath $now", text)
        self.assertIn("if (-not (Test-RuleSignalStillListed $brainPickPath $key)) { continue }", text)
        self.assertIn("[string]$row[0].signal_bar_time -ne [string]$x.signal_bar", text)
        self.assertIn('$PreopenVoiceUntil = [TimeSpan]::Parse("08:59:30")', text)
        self.assertIn("-not $script:priceSourceMismatch -and $publishLiveValues)", text)
        self.assertIn("if ($clock -ge $PreopenVoiceFrom -and $clock -lt $PreopenVoiceUntil) {", text)
        self.assertIn("[VOICE] 08:55 gap voice skipped: covered=", text)
        self.assertIn("[string]$_.rule -in @('R1','R2','R4','R5')", text)
        self.assertIn("ルール5の対象候補です。", text)
        self.assertIn("$spokenRuleSignals=@{}; $spokenNewPicks=@{}; $preopenGapSpoken=$false", text)   # reset each day
        # audit 6325885133: live gate, current-row re-check, cap per cycle, rounding, coverage gate
        self.assertIn("if ($publishLiveValues) {", text)
        self.assertIn("$row[0].aggregate_row_fresh -ne $true -or [string]$row[0].signal -ne [string]$x.signal", text)
        self.assertIn("if ($ruleVoices -ge $MaxRuleVoicesPerCycle) { break }", text)
        self.assertIn("$MaxRuleVoicesPerCycle = 1", text)
        self.assertIn("[Math]::Round([double]$x.entry,1)", text)
        self.assertIn("$preopenCovered -ge $PreopenMinCoverage", text)
        i = text.index("$preopenCovered -ge $PreopenMinCoverage")
        self.assertLess(text.index("$preopenGapSpoken=$true", i), text.index("Add-LoopMark 'voice_tail'"))
        watcher = (ROOT / "ms2_live" / "Kioxia_RSS_Live_Watcher.ps1").read_text(encoding="utf-8-sig")
        self.assertNotIn("キオクシア、買いサイン点灯", watcher)                # OWNER: Kioxia sign voice stopped
        self.assertNotIn("往復ピンタ警戒", text)
        # OWNER 2026-10-22 「音声はIR急騰だけ残して他は止める」
        for gone in ("翌日持ち越しTOP5を確定しました", "後場のOR15維持と引け位置を確認しました", "キオクシア夜間PTS。",
                     "逆指値で発動してください", "\"キオクシア。\"+$kioxia.time_band"):
            self.assertNotIn(gone, text)
        self.assertIn('Invoke-SerializedSpeak $speaker ("IR急騰PTS候補。', text)

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell 5.1 required")
    def test_brain_rule_signal_reader_fails_silent(self):
        harness = r"""
param([string]$Collector, [string]$Dir)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Collector,[ref]$t,[ref]$e)
foreach($name in 'Test-BrainPickFresh','Get-BrainRuleSignals','Test-RuleSignalStillListed'){
  $fn=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
  . ([scriptblock]::Create($fn[0].Extent.Text))
}
$o=[ordered]@{}
# the file was written after an earlier cycle start: judged on the current clock it is fresh,
# judged on a cycle start 10 s ago it would look 10 s in the future and be refused
$o['cycle_start_ref']=(@(Get-BrainRuleSignals (Join-Path $Dir 'valid.json') (Get-Date).AddSeconds(-10)) | ForEach-Object { $_.ticker }) -join ','
$o['pwsh7_datetime']=[string](Test-BrainPickFresh ([datetime]::UtcNow) (Get-Date))
$o['still_listed']=[string](Test-RuleSignalStillListed (Join-Path $Dir 'valid.json') 'A.T||買いサイン||R1')
$o['not_listed']=[string](Test-RuleSignalStillListed (Join-Path $Dir 'valid.json') 'Z.T||買いサイン||R3A_1000')
foreach($n in 'valid','old','future','nooffset','unsafe','stringflag','notlive','oddstate','missing','broken'){ $o[$n]=(@(Get-BrainRuleSignals (Join-Path $Dir ($n+'.json')) (Get-Date)) | ForEach-Object { $_.ticker+':'+$_.rule }) -join ',' }
$o | ConvertTo-Json -Compress
"""
        sig = [{"ticker": "A.T", "rule": "R1", "signal": "買いサイン"}, {"ticker": "Z.T", "rule": "R3A_1000", "signal": "買いサイン"}]
        now = datetime.now(timezone.utc)
        good = {"schema_version": brain.SCHEMA, "real_submit_allowed": False, "trade_instruction": False, "state": "PICK",
                "generated_at": now.isoformat(), "rule_signals": sig}
        files = {"valid": good,
                 "old": dict(good, generated_at=(now - timedelta(seconds=45)).isoformat()),      # by its own generated_at
                 "future": dict(good, generated_at=(now + timedelta(seconds=30)).isoformat()),
                 "nooffset": dict(good, generated_at=now.strftime("%Y-%m-%dT%H:%M:%S")),
                 "unsafe": dict(good, real_submit_allowed=True),
                 "stringflag": dict(good, real_submit_allowed="false"),
                 "notlive": dict(good, state="NOT_LIVE"), "oddstate": dict(good, state="LIVE")}
        with tempfile.TemporaryDirectory() as d:
            for name, doc in files.items():
                (Path(d) / (name + ".json")).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            (Path(d) / "broken.json").write_text("{not json", encoding="utf-8")
            h = Path(d) / "h.ps1"
            h.write_text(harness, encoding="utf-8-sig")
            p = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(h), "-Collector", str(COLLECTOR),
                                "-Dir", d], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(json.loads(p.stdout.strip().splitlines()[-1]),
                         {"cycle_start_ref": "", "pwsh7_datetime": "True", "still_listed": "True", "not_listed": "False",
                          "valid": "A.T:R1", "old": "", "future": "", "nooffset": "", "unsafe": "", "stringflag": "",
                          "notlive": "", "oddstate": "", "missing": "", "broken": ""})


class JpxMarginPass(unittest.TestCase):
    def test_pins_once_a_day_and_fail_closed(self):
        spec = importlib.util.spec_from_file_location("obs_jpx_under_test", ROOT / "scripts" / "ai_brain_observer.py")
        obs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(obs)
        for name, pin in obs.JPX_MODULES:
            self.assertEqual(obs.git_blob_sha1((ROOT / "scripts" / (name + ".py")).read_bytes()), pin)
        calls = []

        class Fake:
            @staticmethod
            def write_cache(runtime, *, now):
                calls.append(now)
                return {"as_of_date": "2026-10-20", "issue_count": 3, "dropped_blocks": 0}
        state = {"module": Fake}
        live_path = Path(tempfile.gettempdir()) / "live_ms2.json"
        self.assertEqual(obs.jpx_margin_pass(state, live_path, now=NOW)["jpx_margin_all"], "BUILT")
        self.assertIsNone(obs.jpx_margin_pass(state, live_path, now=NOW + timedelta(hours=3)))   # once a JST day
        self.assertEqual(len(calls), 1)
        bad = Path(tempfile.mkdtemp(prefix="v10-jpx-bad-"))
        self.addCleanup(shutil.rmtree, bad, True)
        for name, _ in obs.JPX_MODULES:
            (bad / (name + ".py")).write_text("x = 1\n", encoding="utf-8")
        # audit 6327787186: the child is started and polled, never waited for
        state = {}
        self.assertIsNone(obs.jpx_margin_pass(state, live_path, now=NOW, script_dir=bad))
        self.assertIsNotNone(state.get("proc"))
        state["proc"].wait(timeout=60)
        got = obs.jpx_margin_pass(state, live_path, now=NOW + timedelta(seconds=10), script_dir=bad)
        self.assertEqual(got["reason"], "PINNED_MODULE_MISMATCH:agent_sdk_public_feed_ingest")
        self.assertIsNone(state.get("proc"))


class Wiring(unittest.TestCase):
    def test_gateway_route_and_panel(self):
        text = GATEWAY.read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/brain_pick.json') {", text)
        self.assertIn("'100b-v10-brain-pick-v1'", text)
        self.assertIn("'BRAIN_PICK_STALE'", text)
        self.assertIn('<div id="brain-pick-rows">', HTML)
        # 2026-10-22: a second `const renderBrain` in the same script stopped the whole page
        # script (tabs could not be switched). Each top-level name is declared once.
        self.assertEqual(HTML.count("const renderBrain="), 1)
        self.assertEqual(HTML.count("const renderBrainPicks="), 1)
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
