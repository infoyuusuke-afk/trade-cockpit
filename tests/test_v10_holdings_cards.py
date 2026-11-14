"""OWNER 2026-10-23 夜 「コントロールに保有株をカード表示追加、場中、売買したら保有中」「両方 ただし分けて表示」:
real holdings (read-only RSS position lists, this PC only) and simulated holdings as cards in two
separate CONTROL panels. Nothing here may place an order or publish account data. Synthetic checks only."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"
CONTROL_JS = ROOT / "trade_control.js"
WINDOWS = os.name == "nt" and shutil.which("powershell")


def _collector():
    return COLLECTOR.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def _blocks(text):
    setup = text[text.index("# OWNER 2026-10-23 夜 「コントロールに保有株をカード表示追加"):text.index("# 決算・IR開示があった銘柄")]
    start = text.index("# OWNER 2026-10-23 夜: the OWNER's real holdings, read only")
    cycle = text[start:text.index("$script:preopenIdentitySpare = $null", start)]
    return setup, cycle


class ReadOnly(unittest.TestCase):
    def test_only_read_only_list_functions(self):
        setup, cycle = _blocks(_collector())
        self.assertIn("'=RssMarginPositionList(,,\"A\",0,0,0)'", setup)
        self.assertIn("'=RssPositionList(,,\"A\")'", setup)
        self.assertIn("'=RssExecutionList(,0,,\"A\",0,0)'", setup)
        for order_fn in ("Order", "RssStock", "RssMargin" + "OpenOrder", "RssMarginCloseOrder"):
            self.assertNotIn(order_fn, setup + cycle)
        self.assertNotIn(".Formula", cycle)          # the cycle never writes to the workbook
        self.assertEqual(cycle.count(".Value2"), 1)  # one range read

    def test_off_by_default_and_local_only(self):
        setup, cycle = _blocks(_collector())
        self.assertIn('$realPosConfigPath = Join-Path $PSScriptRoot "real_positions_config.json"', setup)
        self.assertIn('[string]$cfg.schema -cne "100b-real-positions-config-v1"', setup)
        self.assertIn('Write-Host "[REAL_POS] OFF (no local real positions config or switched off)"', setup)
        self.assertFalse((ROOT / "ms2_live" / "real_positions_config.json").exists())
        self.assertIn("Write-AtomicUtf8 $realPosFile", cycle)
        # never handed to the public feed, the Brain or an AI
        for path in list((ROOT / "scripts").glob("*.py")) + [ROOT / "downloads" / "START_AI_COCKPIT_V10.ps1"]:
            self.assertNotIn("real_positions", path.read_text(encoding="utf-8-sig", errors="replace"), path.name)
        rest = _collector().replace(setup, "").replace(cycle, "")
        self.assertNotIn("realPos", rest)
        self.assertNotIn("real_positions", rest)

    def test_failure_stops_only_this_read_and_is_retried(self):
        # OWNER 2026-11-06 「口座の読み取りが失敗しても、再起動を待たずに少し置いて自動で読み直して。読めない状態が1分続いたら、声と赤い表示で『口座が読めていません』と知らせる」
        _, cycle = _blocks(_collector())
        self.assertIn('[REAL_POS] WARN / READ FAILED - retry in " + [string]$rpWait + "s (', cycle)
        # OWNER 2026-11-06 「1回の待ち時間を板の読み取りと同じ短さ（約2秒）…失敗が続いたら15秒、30秒、1分と間隔を広げて最長5分…読めたら元に戻す」
        self.assertIn('$rpPacket = Invoke-ExcelCom -Retries 8 -Label "実保有取得"', cycle)
        self.assertIn('Invoke-ExcelCom -Retries 8 -Label "実保有シート確認"', cycle)
        self.assertIn("$rpWait = Get-AccountRetrySeconds $realPosFailCount", cycle)
        self.assertIn("$realPosFailCount = 0\n                $realPosRetryAt = [datetime]::MinValue", cycle)
        # OWNER 2026-11-07 「口座の一覧が空（NOT_READY）のときは成功にせず、負け枠は『読めません』…起動時の失敗も周回で読み直す」
        self.assertIn("if (-not (Test-AccountListsReady $rpMargin $rpExec)) {", cycle)
        self.assertLess(cycle.index("Test-AccountListsReady $rpMargin $rpExec"), cycle.index("Write-AtomicUtf8 $realPosFile"))
        self.assertLess(cycle.index("Write-AtomicUtf8 $realPosFile"), cycle.index("if ($rpFail) {"))
        self.assertIn("$realPosSheet = Initialize-RealPosSheet -Retries 8", cycle)
        self.assertIn("$realPosSetupFailed = $true", _blocks(_collector())[0])
        js = CONTROL_JS.read_text(encoding="utf-8")
        self.assertIn('window.cockpitRealGuard=acct&&acct.margin_state==="OK"&&acct.executions_state==="OK"?', js)
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("!(Number(window.cockpitAccountFailSeconds) >= 60) ? g : null", page)
        self.assertIn("読めません（口座が読めていません）", page)
        self.assertNotIn("throw", cycle)
        self.assertIn("-and (Get-Date) -ge $realPosRetryAt) {", cycle)
        self.assertIn('Join-Path $dayDir "account_read_errors.csv"', cycle)
        self.assertNotIn("$realPosReady = $false\n                $realPosSheet", cycle)
        self.assertIn('Invoke-SerializedSpeak $speaker "口座が読めていません"', cycle)
        self.assertIn("account_read_fail_seconds = $accountReadFailSeconds", _collector())
        self.assertIn("口座が読めていません（", (ROOT / "index.html").read_text(encoding="utf-8"))

    @unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
    def test_lists_ready_only_with_their_headers(self):
        harness = r"""
param([string]$Collector)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Collector,[ref]$t,[ref]$e)
$fn=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-AccountListsReady'},$true))
. ([scriptblock]::Create($fn[0].Extent.Text))
$empty=@()
(Test-AccountListsReady $null $null),(Test-AccountListsReady $null $empty),(Test-AccountListsReady $empty $null),(Test-AccountListsReady $empty $empty),(Test-AccountListsReady @(1) $empty) -join ','
"""
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "h.ps1"
            h.write_text(harness, encoding="utf-8-sig")
            p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(h), "-Collector", str(COLLECTOR)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(p.stdout.strip().splitlines()[-1], "False,False,False,True,True")

    @unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
    def test_retry_wait_grows_to_five_minutes(self):
        harness = r"""
param([string]$Collector)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Collector,[ref]$t,[ref]$e)
$fn=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-AccountRetrySeconds'},$true))
. ([scriptblock]::Create($fn[0].Extent.Text))
(@(0,1,2,3,4,5,6,7,20) | ForEach-Object { Get-AccountRetrySeconds $_ }) -join ','
"""
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "h.ps1"
            h.write_text(harness, encoding="utf-8-sig")
            p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(h), "-Collector", str(COLLECTOR)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(p.stdout.strip().splitlines()[-1], "0,15,30,60,120,240,300,300,300")

    @unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
    def test_block_parser(self):
        text = _collector()
        fns = ""
        for name in ("ConvertFrom-RealPosBlock", "Get-RealPosNumber", "Get-RealPosDate"):
            start = text.index("function " + name)
            fns += text[start:text.index("\n}\n", start) + 2]
        script = fns + r'''
$d = New-Object 'object[,]' 7,4
# 1-based like Excel: use rows 1..6, cols 1..3 (index 0 unused)
$d[1,1] = "配信中"
$d[2,1] = "銘柄コード"; $d[2,2] = "売買"; $d[2,3] = "建玉数量"
$d[3,1] = "285A"; $d[3,2] = "買建"; $d[3,3] = [double]100
$d[4,1] = "6857"; $d[4,2] = "売建"; $d[4,3] = "1,200"
$d[5,1] = $null
$notReady = ConvertFrom-RealPosBlock $d 1 4 3
$rows = ConvertFrom-RealPosBlock $d 2 4 3
Write-Output ("NR=" + ($null -eq $notReady))
Write-Output ("N=" + @($rows).Count)
Write-Output ("A=" + $rows[0]."銘柄コード" + "|" + ($rows[0]."売買" -eq "買建") + "|" + (Get-RealPosNumber $rows[0]."建玉数量"))
Write-Output ("B=" + $rows[1]."銘柄コード" + "|" + (Get-RealPosNumber $rows[1]."建玉数量"))
$e = New-Object 'object[,]' 4,4
$e[1,1] = "銘柄コード"
$empty = ConvertFrom-RealPosBlock $e 1 2 3
Write-Output ("E=" + ($null -eq $empty) + "|" + @($empty).Count)
# OWNER PC 2026-10-24: RSS shows an empty list as one row of dashes in every column
$z = New-Object 'object[,]' 4,4
$z[1,1] = "銘柄コード"; $z[1,2] = "売買"; $z[2,1] = "--------"; $z[2,2] = "--------"
$zr = ConvertFrom-RealPosBlock $z 1 2 3
Write-Output ("Z=" + ($null -eq $zr) + "|" + @($zr).Count)
Write-Output ("D=" + (Get-RealPosDate ([DateTime]::new(2026,10,26).ToOADate())) + "|" + (Get-RealPosDate "2026/10/26 09:01") + "|" + (Get-RealPosDate "2026-1-5") + "|" + (Get-RealPosDate "--------") + "|")
'''
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.ps1"
            p.write_text(script, encoding="utf-8-sig")
            out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(p)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout.split()
        self.assertEqual(out[:7], ["NR=True", "N=2", "A=285A|True|100", "B=6857|1200", "E=False|0", "Z=False|0",
                                   "D=2026/10/26|2026/10/26|2026/01/05||"])


class GatewayRoute(unittest.TestCase):
    def test_route(self):
        text = GATEWAY.read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/real_positions.json') {", text)
        self.assertIn("'100b-v10-real-positions-v1'", text)
        self.assertIn("$view.read_only -ne $true", text)

    @unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
    def test_states(self):
        harness = r"""
param([string]$Gateway, [string]$Dir)
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Gateway,[ref]$t,[ref]$e)
$fn=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-RealPositionsView'},$true))
. ([scriptblock]::Create($fn[0].Extent.Text))
$o=[ordered]@{}; foreach($c in Get-ChildItem -LiteralPath $Dir -Directory){ $o[$c.Name]=(Get-RealPositionsView $c.FullName).status }
$o | ConvertTo-Json -Compress
"""
        good = {"schema_version": "100b-v10-real-positions-v1", "read_only": True, "real_submit_allowed": False,
                "trade_instruction": False, "margin": [], "cash": []}
        cases = {"valid": good, "missing": None, "stale": good,
                 "writable": dict(good, read_only=False), "unsafe": dict(good, real_submit_allowed=True)}
        with tempfile.TemporaryDirectory() as d:
            for name, body in cases.items():
                (Path(d) / name).mkdir()
                if body is not None:
                    f = Path(d) / name / "real_positions_v1.json"
                    f.write_text(json.dumps(body), encoding="utf-8")
                    if name == "stale":
                        old = time.time() - 120
                        os.utime(f, (old, old))
            h = Path(d) / "h.ps1"
            h.write_text(harness, encoding="utf-8-sig")
            p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(h), "-Gateway", str(GATEWAY),
                                "-Dir", d], capture_output=True, text=True, encoding="utf-8", errors="replace")
        got = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(got["valid"], "200 OK")
        for name in ("missing", "stale", "writable", "unsafe"):
            self.assertEqual(got[name], "503 Service Unavailable", name)


class JournalPanels(unittest.TestCase):
    def test_four_panels_in_the_journal_tab(self):
        js = CONTROL_JS.read_text(encoding="utf-8")
        # OWNER 2026-10-23 夜 「保有中、保有した銘柄はAIトレード日記のタブ」
        self.assertIn("const journal=document.querySelector('.tab-pane[data-pane=\"ai-journal\"]');", js)
        for pid, title in (("owner-real-holdings", "保有中｜実口座（読むだけ）"), ("owner-real-closed", "保有した銘柄｜実口座・今日決済"),
                           ("owner-virtual-holdings", "保有中｜仮想（コクピットの検証）"), ("owner-virtual-closed", "保有した銘柄｜仮想・今日決済")):
            self.assertIn('["%s","%s",' % (pid, title), js)
        self.assertIn('fetch("/real_positions.json?t="+Date.now(),{cache:"no-store"})', js)
        self.assertIn('filter(p=>p&&p.status==="OPEN")', js)
        self.assertIn('filter(p=>p&&p.status==="CLOSED"&&p.fill_price!=null)', js)
        self.assertIn("setInterval(renderHoldings,10000);", js)
        self.assertIn("古い保有は表示しません", js)
        self.assertIn("手数料・金利は含まない概算", js)

    def test_swing_and_long_holds_in_the_virtual_panel(self):
        # OWNER 2026-11-10 「保有中にスイング。長期銘柄ない」「スイング 含み益表示」「長期も一緒」
        js = CONTROL_JS.read_text(encoding="utf-8")
        start = js.index("OWNER 2026-11-10 「スイング 含み益表示」")
        block = js[start:js.index('const vDone=document.getElementById("owner-virtual-closed");', start)]
        self.assertIn('fetch("/hold_track.json?t="+Date.now(),{cache:"no-store"})', block)
        self.assertIn("ht&&ht.real_submit_allowed===false", block)          # a file without the flag shows nothing
        self.assertIn('["swing","スイング（仮想）",', block)
        self.assertIn('["value","長期（仮想）",', block)
        self.assertIn("unrealized(code,o.entry,false,true)", block)          # the same 含み益／含み損 line as the other cards
        self.assertIn("の終値）", block)                                    # outside the 100 rows: hold_track's close, labelled
        self.assertIn('["含み（100株）",', block)
        self.assertIn('rules.join("")+overnight.join("")+holds.join("")', block)
        self.assertIn("スイング・長期の仮想保有を読めません", block)
        self.assertNotIn("Order", block)
        self.assertIn("ルール①②④⑤のサイン・オーバーナイト・スイング・長期の仮想売買です。", js)

    def test_pl_amount_coloured_and_note_on_its_own_line(self):
        # OWNER 2026-11-10 「含み益・損の金額を色付き（益・緑／損・赤）　文字の改行位置なおして」
        js = CONTROL_JS.read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('["含み（100株）",y100===null?"—":money(y100),y100>0?"cc-yen-plus":y100<0?"cc-yen-minus":""],', js)
        self.assertIn("""'<b'+(x[2]?' class="'+x[2]+'"':"")+'>'+esc(x[1])""", js)
        self.assertIn('i=s.indexOf("（"),main=i>0?s.slice(0,i):s,note=i>0?s.slice(i+1).replace(/）$/,""):"";', js)
        self.assertIn("""'<small class="cc-pl-note">'+esc(note)+'</small>'""", js)
        self.assertIn(".cc-metrics-grid b.cc-yen-plus{color:#35e2ae}.cc-metrics-grid b.cc-yen-minus{color:#ff5a5f}", html)
        self.assertIn(".cc-pl .cc-pl-main b{white-space:nowrap}", html)
        self.assertIn(".cc-pl{flex-wrap:wrap;column-gap:12px;row-gap:2px}", html)   # 現在値 goes under when it does not fit


if __name__ == "__main__":
    unittest.main()
