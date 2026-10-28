"""Night PTS -> next-morning watch candidates (synthetic records only; no orders)."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts import v10_pts_pickup as pts

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"
HTML = (ROOT / "index.html").read_text(encoding="utf-8").replace("\r\n", "\n")
HEAD = ("captured_at,ticker,name,pts_date,exchange_time,price,tse_close,gap_pct,volume,tse_volume,pts_volume_ratio,"
        "turnover,vwap,bid,ask,spread_pct,bid_qty,ask_qty,over,under,under_ratio,last_tick,bias_score,expectation_score,stance\n")


def row(at, ticker, gap, turnover, spread, stance="翌日上方向注目"):
    return '"%s","%s","n","2026-10-21","%s","1010","1000","%s","100","1","1","%s","1","1","1","%s","1","1","1","1","50","1","30","30","%s"\n' % (
        at, ticker, at[11:], gap, turnover, spread, stance)


def write(records, day, rows):
    d = records / day
    d.mkdir(parents=True, exist_ok=True)
    (d / pts.PTS_FILE).write_text(HEAD + "".join(rows), encoding="utf-8-sig")


class Pickup(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="v10-pts-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.records = Path(tmp) / "records"
        self.records.mkdir()

    def test_latest_snapshot_per_issue_and_criteria(self):
        write(self.records, "2026-10-20", [row("2026-10-20 20:00:00", "1000.JNX", 3.0, 50_000_000, 0.2)])  # older evening
        write(self.records, "2026-10-21", [
            row("2026-10-21 18:00:00", "2000.JNX", 0.5, 50_000_000, 0.2),   # small move at 18:00 ...
            row("2026-10-21 21:00:00", "2000.JNX", 2.5, 50_000_000, 0.2),   # ... latest snapshot moved: kept
            row("2026-10-21 21:00:00", "3000.JNX", -1.8, 20_000_000, 0.5, "翌日下方向警戒"),
            row("2026-10-21 21:00:00", "4000.JNX", 4.0, 5_000_000, 0.2),    # thin: dropped
            row("2026-10-21 21:00:00", "5000.JNX", 4.0, 50_000_000, 2.0),   # wide spread: dropped
            row("2026-10-21 21:00:00", "6000.JNX", 0.4, 90_000_000, 0.1),   # small gap: dropped
        ])
        view = pts.build(self.records, now=datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc))  # 08:00 JST 10/22
        self.assertEqual(view["pts_session_date"], "2026-10-21")
        self.assertEqual(view["recorded_pts_evenings"], 2)
        self.assertEqual([(r["ticker"], r["direction"]) for r in view["rows"]], [("2000.T", "UP"), ("3000.T", "DOWN")])
        self.assertIs(view["trade_instruction"], False)
        self.assertIn("UNVERIFIED", view["verification"])

    def test_nothing_after_now_and_no_records(self):
        write(self.records, "2026-10-21", [row("2026-10-21 21:00:00", "2000.JNX", 2.5, 50_000_000, 0.2)])
        early = pts.build(self.records, now=datetime(2026, 10, 21, 11, 0, tzinfo=timezone.utc))   # 20:00 JST
        self.assertEqual(early["rows"], [])
        empty = Path(tempfile.mkdtemp(prefix="v10-pts-empty-"))
        self.addCleanup(shutil.rmtree, empty, True)
        view = pts.build(empty, now=datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc))
        self.assertEqual((view["pts_session_date"], view["recorded_pts_evenings"], view["rows"]), (None, 0, []))

    def test_side_and_expected_value_from_the_local_table(self):
        # OWNER 2026-10-28 「買い　空売り　期待値　色付け」 (synthetic table, not market data)
        write(self.records, "2026-10-21", [
            row("2026-10-21 21:00:00", "2000.JNX", 2.5, 50_000_000, 0.2),
            row("2026-10-21 21:00:00", "3000.JNX", -3.5, 50_000_000, 0.2),
            row("2026-10-21 21:00:00", "7000.JNX", -3.5, 50_000_000, 0.2),
        ])
        s = lambda n, ev, pf: {"n": n, "ev_pct": ev, "pf": pf}
        table = {"schema_version": pts.EV_SCHEMA, "real_submit_allowed": False, "trade_instruction": False,
                 "overall": {"+2〜3%": {"side": "SKIP", "buy": s(100, -0.1, 0.9), "short": s(100, -0.2, 0.8)},
                             "−3%以下": {"side": "BUY", "buy": s(100, 0.2, 1.1), "short": s(100, -0.4, 0.7)}},
                 "per_stock": {"7000": {"−3%以下": {"buy": s(25, -0.3, 0.8), "short": s(25, 0.1, 1.1)}}}}
        (self.records.parent / pts.EV_FILE).write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
        target = self.records.parent / "pts_pickup_v1.json"
        view = pts.write_pickup(self.records, target, now=datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc))
        got = {r["ticker"]: (r["ev_side"], r["ev_pct"], r["ev_buy_pct"], r["ev_short_pct"], r["ev_basis"]) for r in view["rows"]}
        self.assertEqual(got["2000.T"], ("SKIP", None, -0.1, -0.2, "全体"))
        # OWNER 2026-10-28 「PF1.5以上・回数30以上の時だけ買い・空売りの札」: PF1.1 -> no badge
        self.assertEqual(got["3000.T"], ("SKIP", None, 0.2, -0.4, "全体"))
        # the stock's own numbers (25 times) are under 30: the overall numbers are used
        self.assertEqual(got["7000.T"], ("SKIP", None, 0.2, -0.4, "全体"))
        table["overall"]["−3%以下"]["buy"] = s(100, 0.4, 1.6)
        table["per_stock"]["7000"]["−3%以下"] = {"buy": s(40, 0.5, 1.8), "short": s(40, -0.5, 0.5)}
        (self.records.parent / pts.EV_FILE).write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
        view = pts.write_pickup(self.records, target, now=datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc))
        got = {r["ticker"]: (r["ev_side"], r["ev_pct"], r["ev_basis"]) for r in view["rows"]}
        self.assertEqual(got["3000.T"], ("BUY", 0.4, "全体"))
        self.assertEqual(got["7000.T"], ("BUY", 0.5, "この銘柄"))
        # a table that is not ours or allows orders is ignored: no side at all
        table["real_submit_allowed"] = True
        (self.records.parent / pts.EV_FILE).write_text(json.dumps(table), encoding="utf-8")
        view = pts.write_pickup(self.records, target, now=datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc))
        self.assertTrue(all("ev_side" not in r for r in view["rows"]))

    def test_card_shows_side_ev_and_colour(self):
        self.assertIn('const ptsSide={BUY:["買い","pts-buy"],SHORT:["空売り","pts-short"],SKIP:["見送り","pts-skip"]};', HTML)
        self.assertIn("'<div class=\"pts-ev-row\">'+ptsEvHtml(p)+'</div>'", HTML)
        self.assertIn(".pts-buy{background:#0d2b23;color:#35e2ae}.pts-short{background:#341418;color:#ff5a5f}", HTML)
        self.assertIn("期待値 未計算", HTML)


class Observer(unittest.TestCase):
    def test_pin_and_rebuild_every_five_minutes(self):
        spec = importlib.util.spec_from_file_location("obs_pts_under_test", ROOT / "scripts" / "ai_brain_observer.py")
        obs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(obs)
        name, pin = obs.PTS_PICKUP_MODULE
        self.assertEqual(obs.git_blob_sha1((ROOT / "scripts" / (name + ".py")).read_bytes()), pin)
        tmp = Path(tempfile.mkdtemp(prefix="v10-obs-pts-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "records").mkdir()
        live = tmp / "live_ms2.json"
        state, now = {}, datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc)
        self.assertEqual(obs.pts_pickup_pass(state, live, now=now)["pts_pickup"], "BUILT")
        self.assertIsNone(obs.pts_pickup_pass(state, live, now=now + timedelta(minutes=4)))
        self.assertEqual(obs.pts_pickup_pass(state, live, now=now + timedelta(minutes=6))["pts_pickup"], "BUILT")
        self.assertEqual(json.loads((tmp / obs.PTS_PICKUP_FILE).read_text("utf-8"))["schema_version"], pts.SCHEMA)


class Wiring(unittest.TestCase):
    def test_gateway_route_and_panel(self):
        text = GATEWAY.read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/pts_pickup.json') {", text)
        self.assertIn("'100b-v10-pts-pickup-v1'", text)
        self.assertIn('ptsPanel.id="pts-morning-pickup";', HTML)
        self.assertIn("監視候補で売買サインではありません", HTML)
        self.assertIn("window.cockpitMs2RowReady?.(x)===true", HTML)

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell 5.1 required")
    def test_gateway_states(self):
        harness = r"""
param([string]$Gateway, [string]$Dir)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Gateway,[ref]$t,[ref]$e)
$fn=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-PtsPickupView'},$true))
. ([scriptblock]::Create($fn[0].Extent.Text))
$o=[ordered]@{}; foreach($c in Get-ChildItem -LiteralPath $Dir -Directory){ $o[$c.Name]=(Get-PtsPickupView $c.FullName).status }
$o | ConvertTo-Json -Compress
"""
        good = json.dumps({"schema_version": pts.SCHEMA, "real_submit_allowed": False, "trade_instruction": False, "rows": []})
        with tempfile.TemporaryDirectory() as d:
            for name, text in {"valid": good, "missing": None, "unsafe": good.replace('"real_submit_allowed": false', '"real_submit_allowed": true')}.items():
                (Path(d) / name).mkdir()
                if text is not None:
                    (Path(d) / name / "pts_pickup_v1.json").write_text(text, encoding="utf-8")
            h = Path(d) / "h.ps1"
            h.write_text(harness, encoding="utf-8-sig")
            p = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(h), "-Gateway", str(GATEWAY),
                                "-Dir", d], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(json.loads(p.stdout.strip().splitlines()[-1]),
                         {"missing": "503 Service Unavailable", "unsafe": "503 Service Unavailable", "valid": "200 OK"})


if __name__ == "__main__":
    unittest.main()


class RegimeColour(unittest.TestCase):
    # OWNER 2026-10-28 「色付け」 (地合い判定): spans inside the cells survive the card adapter; VIX / yields are inverted
    def test_good_and_bad_spans(self):
        self.assertIn("const rg = (good, text) => good == null ? text : \"<span class='\" + (good ? \"rg-good\" : \"rg-bad\") + \"'>\" + text + \"</span>\";", HTML)
        self.assertIn("const inverse = n => /VIX|金利/.test(n);", HTML)
        self.assertIn("rg(/^強い/.test(v.label || \"\") ? true : /^弱い/.test(v.label || \"\") ? false : null", HTML)
        self.assertIn(".rg-good{color:#35e2ae!important;font-weight:700}.rg-bad{color:#ff5a5f!important;font-weight:700}", HTML)

    def test_wick_rows_coloured(self):
        # OWNER 2026-10-28 「色付け」 (下ヒゲ吸収反転)
        self.assertIn("const g = t => \"<span class='rg-good'>\" + t + \"</span>\", b = t => \"<span class='rg-bad'>\" + t + \"</span>\";", HTML)
        # OWNER 2026-10-28 「下ヒゲ反転と大口の点数は未検証と書いて緑をやめて」
        self.assertIn('e(x.score) + "/100（未検証）"', HTML)
        self.assertIn('x.score + "/100（未検証）</b>', HTML)
        self.assertNotIn("g(e(x.score)", HTML)
        self.assertNotIn("gs(true, x.score", HTML)
        self.assertIn("b(\"−\" + num(x.fall_from_10d, 1) + \"%\")", HTML)
        self.assertIn("b(yen(x.stop))", HTML)

    def test_accumulation_coloured_with_day_change(self):
        # OWNER 2026-10-28 「色付け　毎日の変化率」 (大口買い集め): 前日比 column from the fed chart's last two closes
        self.assertIn("<th>終値</th><th>前日比</th><th>5日</th>", HTML)
        self.assertIn("const dayChg = x => {", HTML)
        self.assertIn("gs(false, yen(x.stop))", HTML)
