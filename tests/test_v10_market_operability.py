"""P0-V10-MARKET-OPERABILITY-20261019: market-hours diagnostics, synthetic only.

P0-3. Before the first trade of the day the identity row (285A.T) has the
right sheet code but no current price. The Collector reported that as
WRONG_SYMBOL_MAPPING, the same code as a real mapping error. It now reports
IDENTITY_UNTRADED. Both still fail closed (price_source_status is not OK and
no price is published or backfilled); only the name differs.

The identity functions are AST-extracted from the production Collector and
run in Windows PowerShell 5.1 (the production host). The Windows CI job fails
if these tests skip. CI PASS is not a real-machine acceptance.
"""
import json
import os
import shutil
import subprocess
import tempfile
import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
JST = timezone(timedelta(hours=9))

_spec = importlib.util.spec_from_file_location("v10_shadow_supervisor_operability", ROOT / "scripts" / "ai_shadow_supervisor.py")
sup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sup)
_ospec = importlib.util.spec_from_file_location("v10_row_gate_helpers_operability", ROOT / "tests" / "test_v10_row_gate_operability.py")
oper = importlib.util.module_from_spec(_ospec)
_ospec.loader.exec_module(oper)


def _powershell():
    # V10_TEST_POWERSHELL lets a developer run the harness with pwsh locally;
    # CI on Windows always uses Windows PowerShell 5.1.
    override = os.environ.get("V10_TEST_POWERSHELL")
    if override:
        return override
    if os.name != "nt":
        return None
    return shutil.which("powershell")


IDENTITY_HARNESS = r"""
param([string]$Collector, [string]$Cases)
$ErrorActionPreference = 'Stop'
$t = $null; $e = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Collector, [ref]$t, [ref]$e)
if ($e.Count) { throw "PARSE_FAILED" }
foreach ($name in @('Test-PreopenZeroPriceIdentity', 'Get-IdentityQuote', 'Set-IdentityNullPriceState', 'Get-IdentitySourceReason')) {
    $defs = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true))
    if ($defs.Count -ne 1) { throw "HELPER_MISSING $name" }
    . ([scriptblock]::Create($defs[0].Extent.Text))
}
$script:IdentityTicker = "285A.T"
$fixture = [IO.File]::ReadAllText($Cases, [Text.Encoding]::UTF8) | ConvertFrom-Json
$out = [ordered]@{ ps_major = $PSVersionTable.PSVersion.Major; sequences = [ordered]@{} }
foreach ($sequence in $fixture) {
    $steps = New-Object System.Collections.Generic.List[object]
    foreach ($loop in $sequence.loops) {
        # Same order as one Collector loop: reset, row pass, identity quote.
        $script:preopenIdentitySpare = $null
        $script:identityUntraded = $null
        $results = @()
        if ($null -ne $loop.identity_row) {
            $results += [pscustomobject]@{ ticker = "285A.T"; price = $loop.identity_row.price; sheet_code = $loop.identity_row.sheet_code; source_timestamp = $loop.identity_row.time }
        } else {
            Set-IdentityNullPriceState ([bool]$loop.preopen) ([string]$loop.sheet_code) ([string]$loop.time)
        }
        $results += [pscustomobject]@{ ticker = "SYN01.T"; price = 101.0; sheet_code = "SYN01.T"; source_timestamp = "09:00:01" }
        $quote = Get-IdentityQuote $results
        [void]$steps.Add([ordered]@{
            ok = ($quote.ok -eq $true); untraded = ($quote.untraded -eq $true)
            symbol = $quote.symbol; current_price = $quote.current_price; sheet_code = $quote.sheet_code
            source_timestamp = $quote.source_timestamp; reason = (Get-IdentitySourceReason $quote)
        })
    }
    $out.sequences[$sequence.name] = $steps
}
$out | ConvertTo-Json -Depth 6 -Compress
"""


def _untraded(sheet="285A.T", time="15:30:00", preopen=False):
    return {"identity_row": None, "sheet_code": sheet, "time": time, "preopen": preopen}


def _traded(price=1000.0, sheet="285A.T", time="09:00:07"):
    return {"identity_row": {"price": price, "sheet_code": sheet, "time": time}}


SEQUENCES = [
    # Just after 09:00: mapping right, no trade yet (yesterday's time still in the cell).
    ("just_after_open_then_first_trade_then_recovery", [_untraded(), _traded(), _traded(time="09:00:12")]),
    ("time_unknown_untraded", [_untraded(time="")]),
    ("sheet_code_mismatch_without_price", [_untraded(sheet="8035.T")]),
    ("sheet_code_blank_without_price", [_untraded(sheet="")]),
    ("sheet_code_mismatch_with_price", [_traded(sheet="8035.T")]),
    ("preopen_zero_price_spare_unchanged", [_untraded(time="08:05:53", preopen=True)]),
    ("traded_then_untraded_again", [_traded(), _untraded()]),
]


class IdentityUntradedClassification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        exe = _powershell()
        if exe is None:
            raise unittest.SkipTest("Windows PowerShell 5.1 not available; the Windows CI job runs this class")
        tmp = Path(tempfile.mkdtemp(prefix="v10-identity-"))
        try:
            cases = tmp / "cases.json"
            cases.write_text(json.dumps([{"name": n, "loops": loops} for n, loops in SEQUENCES]), encoding="utf-8")
            script = tmp / "harness.ps1"
            script.write_text(IDENTITY_HARNESS, encoding="utf-8-sig")
            proc = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                   "-Collector", str(COLLECTOR), "-Cases", str(cases)], capture_output=True, timeout=120)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            raise AssertionError(out[-2000:] + proc.stderr.decode("utf-8", errors="replace")[-2000:])
        cls.result = json.loads(out.splitlines()[-1].lstrip("﻿"))
        cls.on_windows = os.name == "nt"

    def _steps(self, name):
        return self.result["sequences"][name]

    def test_runs_on_windows_powershell_5(self):
        if self.on_windows:
            self.assertEqual(self.result["ps_major"], 5)

    def test_untraded_identity_has_its_own_reason_and_no_price(self):
        first = self._steps("just_after_open_then_first_trade_then_recovery")[0]
        self.assertEqual(first["reason"], "IDENTITY_UNTRADED")
        self.assertIs(first["ok"], False)
        self.assertIs(first["untraded"], True)
        self.assertEqual(first["symbol"], "285A.T")
        self.assertIsNone(first["current_price"])  # no backfill from the previous close or a quote

    def test_first_trade_and_recovery_are_ok(self):
        _, traded, later = self._steps("just_after_open_then_first_trade_then_recovery")
        for step in (traded, later):
            self.assertIs(step["ok"], True)
            self.assertEqual(step["reason"], "")
            self.assertEqual(step["current_price"], 1000.0)
        self.assertEqual(later["source_timestamp"], "09:00:12")

    def test_unknown_time_is_still_untraded_not_mapping(self):
        step = self._steps("time_unknown_untraded")[0]
        self.assertEqual(step["reason"], "IDENTITY_UNTRADED")
        self.assertIs(step["ok"], False)
        self.assertIsNone(step["current_price"])

    def test_real_mismatch_still_blocks_as_wrong_symbol_mapping(self):
        for name in ("sheet_code_mismatch_without_price", "sheet_code_blank_without_price",
                     "sheet_code_mismatch_with_price"):
            with self.subTest(case=name):
                step = self._steps(name)[0]
                self.assertEqual(step["reason"], "WRONG_SYMBOL_MAPPING")
                self.assertIs(step["ok"], False)
                self.assertIs(step["untraded"], False)
                self.assertIsNone(step["symbol"])

    def test_preopen_spare_behaviour_unchanged(self):
        step = self._steps("preopen_zero_price_spare_unchanged")[0]
        self.assertIs(step["ok"], True)
        self.assertEqual(step["current_price"], 0)
        self.assertEqual(step["reason"], "")

    def test_state_does_not_carry_between_loops(self):
        traded, untraded = self._steps("traded_then_untraded_again")
        self.assertIs(traded["ok"], True)
        self.assertEqual(untraded["reason"], "IDENTITY_UNTRADED")
        self.assertIsNone(untraded["current_price"])


COM_HARNESS = r"""
param([string]$Collector)
$ErrorActionPreference = 'Stop'
$t = $null; $e = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Collector, [ref]$t, [ref]$e)
if ($e.Count) { throw "PARSE_FAILED" }
foreach ($name in @('Get-JstNow', 'Get-ExcelComErrorCode', 'Test-ExcelComBusyCode', 'Add-ExcelComEvent', 'Invoke-ExcelComRead', 'Get-ExcelComReason', 'New-ExcelComFailClosedPayload')) {
    $defs = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true))
    if ($defs.Count -ne 1) { throw "HELPER_MISSING $name" }
    . ([scriptblock]::Create($defs[0].Extent.Text))
}
function Write-Host { }  # keep stdout to the JSON line
function New-Telemetry { [ordered]@{ busy_errors = 0; recovered_reads = 0; failed_reads = 0; other_errors = 0; stopped_reads = 0; consecutive_failed_loops = 0; last_event = $null } }
function Busy { throw [Runtime.InteropServices.COMException]::new("synthetic busy", -2147418111) }
function BusyWrapped { throw [Management.Automation.MethodInvocationException]::new("wrapped", [Runtime.InteropServices.COMException]::new("synthetic busy", -2147418111)) }
function Other { throw [Runtime.InteropServices.COMException]::new("synthetic other", -2146827864) }
$out = [ordered]@{ ps_major = $PSVersionTable.PSVersion.Major; cases = [ordered]@{} }
function Run([string]$Name, [scriptblock]$Action, [scriptblock]$ShouldStop = $null) {
    $script:excelComTelemetry = New-Telemetry
    $script:calls = 0
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-ExcelComRead -Label $Name -Action $Action -MaxAttempts 8 -DelayMilliseconds 100 -ShouldStop $ShouldStop
    $watch.Stop()
    $out.cases[$Name] = [ordered]@{
        ok = $r.ok; value = $(if ($r.ok) { $r.value.Data } else { $null }); attempts = $r.attempts; error_class = $r.error_class
        reason = (Get-ExcelComReason $r); calls = $script:calls; elapsed_ms = [int]$watch.ElapsedMilliseconds
        telemetry = $script:excelComTelemetry
    }
}
Run "normal" { $script:calls++; [pscustomobject]@{ Data = 42 } }
Run "busy_once_then_ok" { $script:calls++; if ($script:calls -eq 1) { Busy }; [pscustomobject]@{ Data = 43 } }
Run "wrapped_busy_once_then_ok" { $script:calls++; if ($script:calls -eq 1) { BusyWrapped }; [pscustomobject]@{ Data = 44 } }
Run "busy_always" { $script:calls++; Busy }
Run "other_error" { $script:calls++; Other }
Run "stop_during_retry" { $script:calls++; Busy } { $script:calls -ge 2 }
$script:excelComTelemetry = New-Telemetry
$script:excelComTelemetry.consecutive_failed_loops = 3
$out.fail_closed_payload = New-ExcelComFailClosedPayload ([datetime]'2026-10-19T09:23:00') 'EXCEL_COM_BUSY'
$out | ConvertTo-Json -Depth 8 -Compress
"""


def run_com_harness(exe):
    tmp = Path(tempfile.mkdtemp(prefix="v10-com-"))
    try:
        script = tmp / "harness.ps1"
        script.write_text(COM_HARNESS, encoding="utf-8-sig")
        proc = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                               "-Collector", str(COLLECTOR)], capture_output=True, timeout=120)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        raise AssertionError(out[-2000:] + proc.stderr.decode("utf-8", errors="replace")[-2000:])
    return json.loads(out.splitlines()[-1].lstrip("﻿"))


class ExcelComBoundedRetry(unittest.TestCase):
    """P0-2: loop reads retry Excel-busy COM errors a bounded number of times."""

    @classmethod
    def setUpClass(cls):
        exe = _powershell()
        if exe is None:
            raise unittest.SkipTest("Windows PowerShell 5.1 not available; the Windows CI job runs this class")
        cls.result = run_com_harness(exe)

    def case(self, name):
        return self.result["cases"][name]

    def test_runs_on_windows_powershell_5(self):
        if os.name == "nt":
            self.assertEqual(self.result["ps_major"], 5)

    def test_normal_read(self):
        c = self.case("normal")
        self.assertIs(c["ok"], True)
        self.assertEqual((c["value"], c["attempts"], c["calls"]), (42, 1, 1))
        self.assertEqual(c["telemetry"]["busy_errors"], 0)
        self.assertIsNone(c["telemetry"]["last_event"])

    def test_one_busy_error_then_recovery_is_counted(self):
        for name, value in (("busy_once_then_ok", 43), ("wrapped_busy_once_then_ok", 44)):
            with self.subTest(case=name):
                c = self.case(name)
                self.assertIs(c["ok"], True)
                self.assertEqual((c["value"], c["attempts"]), (value, 2))
                self.assertEqual(c["telemetry"]["busy_errors"], 1)
                self.assertEqual(c["telemetry"]["recovered_reads"], 1)
                self.assertEqual(c["telemetry"]["failed_reads"], 0)
                self.assertEqual(c["telemetry"]["last_event"]["kind"], "RECOVERED")
                self.assertEqual(c["telemetry"]["last_event"]["code"], "0x80010001")

    def test_consecutive_busy_errors_fail_closed_within_the_bound(self):
        c = self.case("busy_always")
        self.assertIs(c["ok"], False)
        self.assertEqual(c["error_class"], "BUSY")
        self.assertEqual(c["reason"], "EXCEL_COM_BUSY")
        self.assertEqual((c["attempts"], c["calls"]), (8, 8))
        self.assertEqual(c["telemetry"]["busy_errors"], 8)
        self.assertEqual(c["telemetry"]["failed_reads"], 1)
        self.assertEqual(c["telemetry"]["last_event"]["kind"], "FAILED_BUSY")
        # 7 waits of 100 ms; well under the old 60 s retry.
        self.assertLess(c["elapsed_ms"], 5000)

    def test_other_error_is_not_retried(self):
        c = self.case("other_error")
        self.assertIs(c["ok"], False)
        self.assertEqual((c["error_class"], c["reason"], c["calls"]), ("OTHER", "EXCEL_COM_READ_FAILED", 1))
        self.assertEqual(c["telemetry"]["other_errors"], 1)

    def test_stop_request_ends_the_retry(self):
        c = self.case("stop_during_retry")
        self.assertIs(c["ok"], False)
        self.assertEqual(c["error_class"], "STOPPED")
        self.assertEqual(c["calls"], 2)
        self.assertEqual(c["telemetry"]["stopped_reads"], 1)
        self.assertLess(c["elapsed_ms"], 2000)

    def test_fail_closed_payload_carries_no_market_values(self):
        p = self.result["fail_closed_payload"]
        self.assertEqual(p["price_source_status"], "EXCEL_COM_BUSY")
        self.assertEqual(p["stale_reason"], "EXCEL_COM_BUSY")
        self.assertIs(p["stale"], True)
        self.assertIs(p["live_values_available"], False)
        self.assertIs(p["real_submit_allowed"], False)
        self.assertEqual(p["valid"], 0)
        for key in ("all_targets", "top5", "hold_top5", "pts_top5", "ir_pts_top5"):
            self.assertEqual(p[key], [], key)
        for key in ("kioxia", "market_state", "breadth_pct"):
            self.assertNotIn(key, p)
        self.assertIsNone(p["live_price_diagnostics"]["current_price"])
        self.assertEqual(p["live_price_diagnostics"]["excel_com"]["consecutive_failed_loops"], 3)
        # The Shadow supervisor refuses it and names the COM failure.
        now = datetime(2026, 10, 19, 9, 23, 0, tzinfo=JST)
        payload = dict(p, updated_at=now.isoformat())
        verdict = sup.assess_live_payload(payload, file_mtime=now, now=now)
        self.assertIs(verdict["ok"], False)
        self.assertIn("EXCEL_COM_BUSY", verdict["reasons"])
        self.assertEqual(sup._component_for("EXCEL_COM_BUSY"), "price_source")

MISSING_HARNESS = r"""
param([string]$Collector)
$ErrorActionPreference = 'Stop'
$t = $null; $e = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Collector, [ref]$t, [ref]$e)
$defs = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'New-MissingRowRecord' }, $true))
if ($defs.Count -ne 1) { throw "HELPER_MISSING" }
. ([scriptblock]::Create($defs[0].Extent.Text))
@(
    (New-MissingRowRecord "SYN42.T" "syn42.t " ""),
    (New-MissingRowRecord "SYN43.T" "8035.T" "15:00:00"),
    (New-MissingRowRecord "SYN44.T" "" "")
) | ConvertTo-Json -Depth 4 -Compress
"""


class CollectorMissingRows(unittest.TestCase):
    """P0-5: a watchlist row with no price is published as a missing row."""

    def test_missing_row_records(self):
        exe = _powershell()
        if exe is None:
            self.skipTest("Windows PowerShell 5.1 not available; the Windows CI job runs this test")
        tmp = Path(tempfile.mkdtemp(prefix="v10-missing-"))
        try:
            script = tmp / "harness.ps1"
            script.write_text(MISSING_HARNESS, encoding="utf-8-sig")
            proc = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                   "-Collector", str(COLLECTOR)], capture_output=True, timeout=120)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", errors="replace")[-2000:])
        records = json.loads(proc.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1].lstrip("﻿"))
        right, wrong, blank = records
        self.assertEqual((right["ticker"], right["reason"], right["sheet_code_matches"]), ("SYN42.T", "PRICE_MISSING", True))
        self.assertIsNone(right["source_time_text"])
        self.assertEqual((wrong["sheet_code_matches"], wrong["source_time_text"]), (False, "15:00:00"))
        self.assertIs(blank["sheet_code_matches"], False)
        for r in records:
            self.assertIsNone(r["price"])
            self.assertEqual(set(r), {"ticker", "reason", "sheet_code_matches", "source_time_text", "price"})

class ShadowUntradedIdentity(unittest.TestCase):
    """The Shadow supervisor blocks an untraded identity and names it."""

    def _payload(self, stale_reason):
        now = datetime(2026, 10, 19, 9, 0, 30, tzinfo=JST)
        diag = {"price_source_status": "PRICE_SOURCE_MISMATCH", "source_mode": "MS2_RSS_WORKBOOK",
                "workbook_name": sup.CANONICAL_WORKBOOK, "data_conflict": True, "duplicate_collector": False,
                "duplicate_watcher": False, "collector_count": 1, "watcher_count": 0,
                "stale_reason": stale_reason, "symbol": "285A.T", "current_price": None,
                "live_values_available": False}
        payload = {"real_submit_allowed": False, "live_values_available": False,
                   "price_source_status": "PRICE_SOURCE_MISMATCH", "source": sup.CANONICAL_SOURCE,
                   "source_mode": "MS2_RSS_WORKBOOK", "data_conflict": True, "stale": True,
                   "updated_at": now.isoformat(), "live_price_diagnostics": diag, "all_targets": []}
        return payload, now

    def test_untraded_is_blocked_and_named(self):
        payload, now = self._payload("IDENTITY_UNTRADED")
        verdict = sup.assess_live_payload(payload, file_mtime=now, now=now)
        self.assertIs(verdict["ok"], False)
        self.assertIs(verdict["real_submit_allowed"], False)
        self.assertIn("IDENTITY_UNTRADED", verdict["reasons"])
        self.assertNotIn("WRONG_SYMBOL_MAPPING", verdict["reasons"])
        self.assertEqual(sup._primary_reason(verdict["reasons"]), "IDENTITY_UNTRADED")
        self.assertEqual(sup._component_for("IDENTITY_UNTRADED"), "price_source")

    def test_real_mismatch_takes_precedence(self):
        payload, now = self._payload("IDENTITY_UNTRADED,WRONG_SYMBOL_MAPPING")
        verdict = sup.assess_live_payload(payload, file_mtime=now, now=now)
        self.assertIs(verdict["ok"], False)
        self.assertIn("IDENTITY_UNTRADED", verdict["reasons"])
        self.assertIn("WRONG_SYMBOL_MAPPING", verdict["reasons"])
        self.assertEqual(sup._primary_reason(verdict["reasons"]), "WRONG_SYMBOL_MAPPING")

class ShadowFreshOnlyEvaluation(unittest.TestCase):
    """P0-4 (plan A, shadow only): observation PASS and decision PASS are
    reported apart, and a fresh-rows-only evaluation is recorded without
    changing the whole-board decision."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v10-fresh-only-"))
        oper.write_watchlist(self.tmp)
        self.data = self.tmp / "ai_shadow"
        self.live = self.tmp / "live_ms2.json"
        self.status = self.tmp / "ai_shadow_status.json"
        self.t0 = datetime(2026, 10, 19, 10, 0, 5, tzinfo=JST)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _record(self, payload):
        self.live.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.utime(self.live, (self.t0.timestamp(), self.t0.timestamp()))
        engine = sup.run_once(self.data, self.live, self.status, now=self.t0)
        lines = (self.data / "board_availability.jsonl").read_text(encoding="utf-8").splitlines()
        return engine, json.loads(lines[-1])

    def _top5(self, payload, *tickers):
        rows = {r["ticker"]: r for r in payload["all_targets"]}
        payload["top5"] = [rows[t] for t in tickers if t in rows] + [{"ticker": t} for t in tickers if t not in rows]
        return payload

    def test_all_fresh_both_pass(self):
        _, record = self._record(self._top5(oper.board(self.t0), "SYN01.T", "SYN02.T"))
        self.assertIs(record["observation_pass"], True)
        self.assertIs(record["decision_available"], True)
        self.assertIs(record["decision_pass"], True)
        shadow = record["shadow_fresh_only"]
        self.assertIs(shadow["would_be_decidable"], True)
        self.assertEqual((shadow["candidates_published"], shadow["candidates_with_fresh_inputs"]), (2, 2))
        self.assertIs(shadow["applied_to_decision"], False)

    def test_one_stale_candidate_is_invalidated_and_whole_board_rule_is_unchanged(self):
        payload = self._top5(oper.board(self.t0, stale={"SYN02.T"}), "SYN01.T", "SYN02.T")
        engine, record = self._record(payload)
        self.assertIs(record["observation_pass"], True)
        self.assertIs(record["decision_available"], False)  # existing fail-closed rule kept
        self.assertIs(record["decision_pass"], False)
        shadow = record["shadow_fresh_only"]
        self.assertEqual(shadow["fresh_pct"], 99.0)
        self.assertIs(shadow["would_be_decidable"], True)
        self.assertEqual(shadow["candidates_with_fresh_inputs"], 1)
        self.assertEqual(shadow["candidate_invalidation_reasons"], {"CANDIDATE_ROW_NOT_FRESH": 1})
        self.assertEqual(shadow["aggregates"], "WITHHELD_NOT_RECOMPUTED")
        self.assertEqual([e for e in engine["ledger"] if e.get("event_type") == "virtual_entry"], [])

    def test_99_of_100_is_never_100_and_missing_is_named(self):
        payload = self._top5(oper.board(self.t0, drop={"SYN42.T"}, declared=100), "SYN42.T", "SYN01.T")
        payload["missing_rows"] = [{"ticker": "SYN42.T", "reason": "PRICE_MISSING", "sheet_code_matches": True,
                                    "source_time_text": None, "price": None}]
        _, record = self._record(payload)
        self.assertIs(record["decision_available"], False)
        self.assertEqual(record["missing_tickers"], ["SYN42.T"])
        self.assertIs(record["observation_pass"], True)
        self.assertEqual(record["collector_missing_rows"], {"published": True, "count": 1, "sheet_code_mismatch": 0})
        shadow = record["shadow_fresh_only"]
        self.assertEqual((shadow["expected_count"], shadow["fresh_count"], shadow["fresh_pct"]), (100, 99, 99.0))
        self.assertEqual(shadow["candidate_invalidation_reasons"], {"CANDIDATE_ROW_MISSING": 1})

    def test_too_few_fresh_rows_is_not_representative(self):
        stale = set(oper.UNIVERSE[90:])
        _, record = self._record(oper.board(self.t0, stale=stale))
        shadow = record["shadow_fresh_only"]
        self.assertEqual(shadow["fresh_pct"], 90.0)
        self.assertIs(shadow["would_be_decidable"], False)
        self.assertIn("FRESH_ROWS_NOT_REPRESENTATIVE", shadow["reasons"])

    def test_stale_identity_is_not_decidable(self):
        _, record = self._record(oper.board(self.t0, identity_at=self.t0 - timedelta(minutes=5)))
        shadow = record["shadow_fresh_only"]
        self.assertIs(shadow["would_be_decidable"], False)
        self.assertIn("IDENTITY_QUOTE_NOT_FRESH", shadow["reasons"])

    def test_source_failure_is_not_an_observation_pass(self):
        payload = oper.board(self.t0)
        payload["price_source_status"] = "EXCEL_COM_BUSY"
        _, record = self._record(payload)
        self.assertIs(record["source_checks_pass"], False)
        self.assertIs(record["observation_pass"], False)
        self.assertIs(record["decision_pass"], False)


class ServedHistoryFirstRunAcceptance(unittest.TestCase):
    """GPT review of 6c0758a, blocker A: an empty served history is accepted
    only explicitly, and no production launcher ever does so."""

    def test_production_launchers_never_accept_an_empty_history(self):
        for rel in ("downloads/AI_COCKPIT_CONTROLLER_V10.ps1", "downloads/RUN_AI_COCKPIT_V10.ps1",
                    "downloads/START_AI_COCKPIT_V10.ps1", "downloads/STOP_AI_COCKPIT_V10.ps1",
                    "downloads/START_AI_COCKPIT_V10.cmd", "downloads/STOP_AI_COCKPIT_V10.cmd"):
            with self.subTest(file=rel):
                text = (ROOT / rel).read_text(encoding="utf-8-sig", errors="replace")
                self.assertNotIn("ServedHistoryBootstrap", text)
                self.assertNotIn("ACCEPT_EMPTY_HISTORY", text)

    def test_gateway_guards_the_acceptance_and_the_history_lock(self):
        text = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('[ValidateSet("", "ACCEPT_EMPTY_HISTORY")][string]$ServedHistoryBootstrap = ""', text)
        # Honoured only without a history or lock file in the directory.
        self.assertIn('($script:ServedHistoryState -ceq "NO_HISTORY_FILE") -and -not $script:ServedHistoryPriorEvidence', text)
        self.assertIn("$lock = Enter-ServedHistoryLock $Path", text)
        self.assertIn("[IO.FileShare]::None", text.split("function Enter-ServedHistoryLock", 1)[1].split("function ", 1)[0])


GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"

INTERLEAVE_HARNESS = r"""
param([string]$Gateway)
$ErrorActionPreference = 'Stop'
$t = $null; $e = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Gateway, [ref]$t, [ref]$e)
foreach ($f in $ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($f.Name -match 'ServedHistory|OffsetTimestamp|BytesSha256|SharingViolation|QuoteAt|StartFloor') { . ([scriptblock]::Create($f.Extent.Text)) }
}
if ($PSVersionTable.PSVersion.Major -ge 6) {
    # Local pwsh runs only: keep ISO strings as strings like Windows
    # PowerShell 5.1, and treat flock contention (EAGAIN) as a sharing violation.
    function ConvertFrom-Json { param([Parameter(ValueFromPipeline = $true)][string]$InputObject) process { $o = Microsoft.PowerShell.Utility\ConvertFrom-Json -InputObject ($InputObject -replace '"(\d{4}-\d{2}-\d{2}T)', '"~$1'); foreach ($p in @($o.PSObject.Properties)) { if ($p.Value -is [string] -and $p.Value.StartsWith('~')) { $p.Value = $p.Value.Substring(1) } elseif ($p.Value -is [pscustomobject]) { foreach ($q in @($p.Value.PSObject.Properties)) { if ($q.Value -is [string] -and $q.Value.StartsWith('~')) { $q.Value = $q.Value.Substring(1) } } } }; $o } }
    function Test-SharingViolation($ErrorRecord) { $i = $ErrorRecord.Exception; while ($null -ne $i -and -not ($i -is [IO.IOException])) { $i = $i.InnerException }; return ($null -ne $i -and @(-2147024864, -2147024863, 11) -contains $i.HResult) }
}
$dir = Join-Path ([IO.Path]::GetTempPath()) ('v10-interleave-' + [guid]::NewGuid().ToString('N'))
[void](New-Item -ItemType Directory $dir)
$path = Join-Path $dir 'v10_gateway_served_quotes.json'
$out = [ordered]@{}
try {
    $base = Save-ServedHistory $path '2026-10-19T10:00:00+09:00' @{ A = '2026-10-19T10:00:00+09:00' } @('A') $null $false ''
    $start = $base.disk_sha256
    # Gateway A (10:00:10) and Gateway B (10:00:20) both checked the board
    # against history $start. B's whole save is forced in between A's
    # checks and A's replace.
    $script:b = $null
    $realIo = ${function:Invoke-ServedHistoryIo}
    function Invoke-ServedHistoryIo([scriptblock]$Action) {
        if ($null -eq $script:b -and $Action.ToString() -match 'Replace\(\$temporary, \$Path') {
            $script:b = Save-ServedHistory $path '2026-10-19T10:00:20+09:00' @{ A = '2026-10-19T10:00:20+09:00' } @('A') $start $true ''
        }
        & $realIo $Action
    }
    $a = Save-ServedHistory $path '2026-10-19T10:00:10+09:00' @{ A = '2026-10-19T10:00:10+09:00' } @('A') $start $true ''
    Remove-Item function:Invoke-ServedHistoryIo
    Set-Item function:Invoke-ServedHistoryIo $realIo
    $out.a_ok = $a.ok
    $out.b_ok = $script:b.ok
    $out.b_reason = $script:b.reason
    $out.disk_identity = ((ConvertFrom-ServedHistoryContent ([IO.File]::ReadAllBytes($path))).identity)
    $evidence = Read-ServedHistoryEvidence $path
    $out.evidence_matches_disk = (Test-ServedHistoryEvidenceMatch $evidence (Get-BytesSha256 ([IO.File]::ReadAllBytes($path))))
    $out.evidence_generation = $evidence.generation
    # B retries after A released the lock, from its old history: it merges
    # A's verified history and saves its newer quote on top.
    $retry = Save-ServedHistory $path '2026-10-19T10:00:20+09:00' @{ A = '2026-10-19T10:00:20+09:00' } @('A') $start $true ''
    $out.retry_ok = $retry.ok
    $out.retry_peer = ($null -ne $retry.peer)
    $out.retry_identity = ((ConvertFrom-ServedHistoryContent ([IO.File]::ReadAllBytes($path))).identity)
    # A then tries an older quote from its stale view: refused, disk unchanged.
    $stale = Save-ServedHistory $path '2026-10-19T10:00:15+09:00' @{ A = '2026-10-19T10:00:15+09:00' } @('A') $a.disk_sha256 $true ''
    $out.stale_reason = $stale.reason
    $out.stale_detail = $stale.detail
    $out.final_identity = ((ConvertFrom-ServedHistoryContent ([IO.File]::ReadAllBytes($path))).identity)
    $out.temporaries = @(Get-ChildItem -LiteralPath $dir -Filter '*.tmp').Count
} finally {
    Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
}
$out | ConvertTo-Json -Compress
"""


@unittest.skipUnless(_powershell(), "needs Windows PowerShell 5.1 (CI) or V10_TEST_POWERSHELL")
class ServedHistoryInterleaving(unittest.TestCase):
    """GPT review of 6c0758a, blocker B: a save forced in between another
    Gateway's checks and its replace cannot lower the history on disk."""

    @classmethod
    def setUpClass(cls):
        tmp = Path(tempfile.mkdtemp(prefix="v10-interleave-"))
        try:
            script = tmp / "harness.ps1"
            script.write_text(INTERLEAVE_HARNESS, encoding="utf-8-sig")
            proc = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                   str(script), "-Gateway", str(GATEWAY)], capture_output=True, timeout=120)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            raise AssertionError(out[-2000:] + proc.stderr.decode("utf-8", errors="replace")[-2000:])
        cls.result = json.loads(out.splitlines()[-1].lstrip("﻿"))

    def test_the_interleaved_save_waits_and_is_refused(self):
        # Without the lock (6c0758a) both saves returned ok and the disk went
        # back from 10:00:20 to 10:00:10 after 10:00:20 had been served.
        self.assertIs(self.result["a_ok"], True)
        self.assertIs(self.result["b_ok"], False)
        self.assertEqual(self.result["b_reason"], "SERVED_HISTORY_LOCK_TIMEOUT")
        self.assertEqual(self.result["disk_identity"], "2026-10-19T10:00:10+09:00")
        self.assertIs(self.result["evidence_matches_disk"], True)
        self.assertEqual(self.result["evidence_generation"], 2)

    def test_a_retry_merges_the_verified_history_and_moves_forward(self):
        self.assertIs(self.result["retry_ok"], True)
        self.assertIs(self.result["retry_peer"], True)
        self.assertEqual(self.result["retry_identity"], "2026-10-19T10:00:20+09:00")

    def test_an_older_quote_from_a_stale_view_cannot_overwrite(self):
        self.assertEqual(self.result["stale_reason"], "SERVED_HISTORY_PEER_NEWER")
        self.assertIn("SOURCE_TIMESTAMP_REGRESSION", self.result["stale_detail"].split(","))
        self.assertEqual(self.result["final_identity"], "2026-10-19T10:00:20+09:00")
        self.assertEqual(self.result["temporaries"], 0)


if __name__ == "__main__":
    unittest.main()
