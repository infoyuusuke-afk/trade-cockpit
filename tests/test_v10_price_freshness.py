"""P0-V10-ACCEPTANCE-FIX-20261019: an old quote is never a fresh quote.

Synthetic data only. The 2026-10-19 Windows acceptance saw a Friday 15:30
quote rewritten every 2 seconds and reported fresh at Monday 02:14 JST,
because freshness was judged from writer time (updated_at, file mtime).

The shared cases in tests/fixtures/v10_price_freshness_cases.json run here
against the Shadow supervisor (Python) and, in the PowerShell class below,
against the V10 Gateway /health implementation and the Collector's quote
dating, so the components cannot drift apart silently.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests" / "fixtures" / "v10_price_freshness_cases.json").read_text(encoding="utf-8"))
JST = timezone(timedelta(hours=9))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sup = _load("v10_shadow_supervisor_under_test", "scripts/ai_shadow_supervisor.py")
rg = _load("v10_risk_gate_under_test", "scripts/risk_gate.py")


def _ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _payload(diag, rows=None):
    return {"live_price_diagnostics": dict(diag), "all_targets": list(rows or [])}


def _verdict(case):
    return sup.assess_quote_freshness(
        _payload(case["diag"], case.get("rows")),
        now=_ts(case["now"]),
        previous_quote_at=case.get("previous_quote_at"),
    )


CASE_BY_NAME = {c["name"]: c for c in CASES["cases"]}


class SharedFreshnessCases(unittest.TestCase):
    def test_every_shared_case(self):
        self.assertGreaterEqual(len(CASES["cases"]), 19)
        for case in CASES["cases"]:
            with self.subTest(case=case["name"]):
                got = _verdict(case)
                self.assertEqual(got["state"], case["expect"]["state"])
                self.assertEqual(got["reasons"], sorted(case["expect"]["reasons"]))
                self.assertIs(got["fresh"], case["expect"]["state"] == "FRESH")
                self.assertIs(got["real_submit_allowed"], False)
                self.assertIs(got["order_allowed"], False)
                if "market_session" in case["expect"]:
                    self.assertEqual(got["market_session"], case["expect"]["market_session"])
                if "quote_at" in case["expect"]:
                    self.assertEqual(got["quote_at"], case["expect"]["quote_at"])

    def test_combined_shadow_and_health(self):
        for item in CASES["combined"]:
            with self.subTest(case=item["name"]):
                a = _verdict(CASE_BY_NAME[item["a"]])
                b = _verdict(CASE_BY_NAME[item["b"]]) if item["b"] else None
                ok, reasons = sup.combined_freshness(a, b)
                self.assertIs(ok, item["expect_fresh"])
                self.assertEqual(reasons, sorted(item["expect_reasons"]))

    def test_naive_now_is_rejected(self):
        got = sup.assess_quote_freshness(_payload(CASE_BY_NAME["normal_fresh_quote"]["diag"]),
                                         now=datetime(2026, 10, 19, 10, 0, 5))
        self.assertEqual(got["state"], "INVALID")
        self.assertIn("NOW_NOT_TIMEZONE_AWARE", got["reasons"])

    def test_closed_market_is_separate_from_freshness(self):
        # A fresh quote stays fresh at 15:30:30 (after close); the session
        # label changes but freshness is decided by quote age only.
        diag = {"source_timestamp": "15:30:00", "source_timestamp_at": "2026-10-16T15:30:00+09:00",
                "source_timestamp_basis": "COLLECTOR_OBSERVED_CHANGE",
                "source_timestamp_observed_at": "2026-10-16T15:30:01+09:00"}
        got = sup.assess_quote_freshness(_payload(diag), now=_ts("2026-10-16T15:31:00+09:00"))
        self.assertEqual(got["state"], "FRESH")
        self.assertEqual(got["market_session"], "CLOSED_OUTSIDE_HOURS")
        self.assertIs(got["order_allowed"], False)


def _full_payload(now, diag, stale=False):
    """A payload that passes every non-freshness check of assess_live_payload."""
    base_diag = {
        "price_source_status": "OK", "source_mode": "MS2_RSS_WORKBOOK",
        "workbook_name": "Kioxia_MS2_RSS_Live_Signals.xlsx", "data_conflict": False,
        "duplicate_collector": False, "duplicate_watcher": False, "collector_count": 1,
        "watcher_count": 1, "stale_reason": "", "symbol": "285A.T",
    }
    base_diag.update(diag)
    return {
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "MarketSpeed II RSS / local PC", "source_mode": "MS2_RSS_WORKBOOK",
        "stale": stale, "stale_reason": "", "data_conflict": False, "price_source_status": "OK",
        "live_values_available": True, "real_submit_allowed": False,
        "live_price_diagnostics": base_diag,
        "all_targets": [{"ticker": "SYN1.T", "signal": "待機", "price": 100.0, "data": "LIVE",
                         "source_timestamp": diag.get("source_timestamp")}],
    }


class SupervisorIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v10-fresh-"))
        self.data = self.tmp / "ai_shadow"
        self.live = self.tmp / "live_ms2.json"
        self.status = self.tmp / "ai_shadow_status.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, payload, mtime):
        self.live.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.utime(self.live, (mtime.timestamp(), mtime.timestamp()))

    def test_friday_quote_rewritten_monday_is_fail_closed(self):
        now = _ts("2026-10-19T02:14:00+09:00")
        payload = _full_payload(now, CASE_BY_NAME["friday_close_republished_monday_0214"]["diag"])
        verdict = sup.assess_live_payload(payload, file_mtime=now, now=now)
        self.assertFalse(verdict["ok"])
        self.assertIn("STALE_SOURCE_QUOTE", verdict["reasons"])
        # The Collector claimed stale=False: that disagreement is recorded.
        self.assertIn("FRESHNESS_VERDICT_MISMATCH", verdict["reasons"])
        self.assertIs(verdict["real_submit_allowed"], False)

    def test_mtime_and_updated_at_alone_never_make_fresh(self):
        now = _ts("2026-10-19T10:20:00+09:00")
        payload = _full_payload(now, CASE_BY_NAME["old_quote_only_mtime_refreshed"]["diag"])
        self._write(payload, now)
        engine = sup.run_once(self.data, self.live, self.status, now=now)
        status = json.loads(self.status.read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "PAUSED_FAIL_CLOSED")
        self.assertEqual(status["quote_freshness"]["state"], "STALE")
        self.assertIs(status["real_submit_allowed"], False)
        self.assertEqual(engine["ledger"], [])

    def test_time_only_payload_like_acceptance_is_fail_closed(self):
        now = _ts("2026-10-19T02:14:00+09:00")
        payload = _full_payload(now, {"source_timestamp": "15:30:00"})
        self._write(payload, now)
        sup.run_once(self.data, self.live, self.status, now=now)
        status = json.loads(self.status.read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "PAUSED_FAIL_CLOSED")
        self.assertEqual(status["quote_freshness"]["reasons"], ["SOURCE_DATE_UNKNOWN"])

    def test_fresh_quote_runs_and_recovers_after_stale(self):
        stale_now = _ts("2026-10-19T09:00:30+09:00")
        old = {"source_timestamp": "15:30:00", "source_timestamp_at": "2026-10-16T15:30:00+09:00",
               "source_timestamp_basis": "COLLECTOR_OBSERVED_CHANGE",
               "source_timestamp_observed_at": "2026-10-16T15:30:01+09:00"}
        self._write(_full_payload(stale_now, old), stale_now)
        sup.run_once(self.data, self.live, self.status, now=stale_now)
        self.assertEqual(json.loads(self.status.read_text(encoding="utf-8"))["state"], "PAUSED_FAIL_CLOSED")

        fresh_now = _ts("2026-10-19T09:00:35+09:00")
        new = {"source_timestamp": "09:00:33", "source_timestamp_at": "2026-10-19T09:00:33+09:00",
               "source_timestamp_basis": "COLLECTOR_OBSERVED_CHANGE",
               "source_timestamp_observed_at": "2026-10-19T09:00:34+09:00"}
        self._write(_full_payload(fresh_now, new), fresh_now)
        engine = sup.run_once(self.data, self.live, self.status, now=fresh_now)
        status = json.loads(self.status.read_text(encoding="utf-8"))
        self.assertIn(status["state"], ("RUNNING", "RECOVERING"))
        self.assertEqual(status["quote_freshness"]["state"], "FRESH")
        self.assertEqual(engine["state"]["last_fresh_quote_at"], "2026-10-19T09:00:33+09:00")

        # A later cycle that goes back in time is refused, not healed.
        back_now = _ts("2026-10-19T09:00:40+09:00")
        back = dict(new, source_timestamp="09:00:20", source_timestamp_at="2026-10-19T09:00:20+09:00",
                    source_timestamp_observed_at="2026-10-19T09:00:39+09:00")
        self._write(_full_payload(back_now, back), back_now)
        sup.run_once(self.data, self.live, self.status, now=back_now)
        status = json.loads(self.status.read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "PAUSED_FAIL_CLOSED")
        self.assertIn("SOURCE_TIMESTAMP_REGRESSION", status["quote_freshness"]["reasons"])

    def test_old_quote_never_creates_virtual_entry(self):
        now = _ts("2026-10-19T02:14:00+09:00")
        payload = _full_payload(now, CASE_BY_NAME["friday_close_republished_monday_0214"]["diag"])
        payload["all_targets"] = [{"ticker": "SYN1.T", "signal": "買いサイン", "strategy": "synthetic",
                                   "price": 100.0, "entry_price": 100.0, "stop_price": 95.0,
                                   "data": "LIVE", "source_timestamp": "15:30:00"}]
        self._write(payload, now)
        engine = sup.run_once(self.data, self.live, self.status, now=now)
        self.assertEqual(engine["open_positions"], {})
        self.assertEqual([e for e in engine["ledger"] if e.get("event_type") == "virtual_entry"], [])


IDENTITY_FRESH = {"source_timestamp": "10:00:01", "source_timestamp_at": "2026-10-19T10:00:01+09:00",
                  "source_timestamp_basis": "COLLECTOR_OBSERVED_CHANGE",
                  "source_timestamp_observed_at": "2026-10-19T10:00:02+09:00"}


def _signal_row(ticker, signal, quote):
    row = {"ticker": ticker, "signal": signal, "strategy": "synthetic", "price": 100.0,
           "entry_price": 100.0, "stop_price": 95.0, "data": "LIVE"}
    row.update(quote)
    return row


def _row_quote(at, observed=None, basis="COLLECTOR_OBSERVED_CHANGE"):
    if at is None:
        return {"source_timestamp": "09:55:00", "source_timestamp_at": None,
                "source_timestamp_basis": "UNOBSERVED_SINCE_START", "source_timestamp_observed_at": None}
    return {"source_timestamp": at[11:19], "source_timestamp_at": at, "source_timestamp_basis": basis,
            "source_timestamp_observed_at": observed or at}


SYNTHETIC_UNIVERSE = ["SYN%d.T" % i for i in range(100)]


def write_synthetic_watchlist(directory):
    stocks = {"synthetic %03d" % i: {"ticker": t, "sector": "synthetic"} for i, t in enumerate(SYNTHETIC_UNIVERSE)}
    (Path(directory) / "watchlist_100.json").write_text(json.dumps({"stocks": stocks}), encoding="utf-8")


def complete_board(rows, now):
    """The given rows plus a fresh, signal-free row for every other synthetic ticker."""
    given = {r["ticker"] for r in rows}
    at = (now - timedelta(seconds=1)).isoformat(timespec="seconds")
    padding = [_signal_row(t, "待機", _row_quote(at)) for t in SYNTHETIC_UNIVERSE if t not in given]
    return list(rows) + padding


class PerRowFreshness(unittest.TestCase):
    """A fresh board does not make every row's price fresh.

    Each cycle publishes a complete 100-row synthetic board, so that only the
    rows under test decide the outcome (a short board is never decision
    available)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v10-row-"))
        self.data = self.tmp / "ai_shadow"
        self.live = self.tmp / "live_ms2.json"
        self.status = self.tmp / "ai_shadow_status.json"
        self.now = _ts("2026-10-19T10:00:05+09:00")
        write_synthetic_watchlist(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cycle(self, rows, now=None, identity=None, updated=None):
        now = now or self.now
        payload = _full_payload(now, identity or IDENTITY_FRESH)
        payload["all_targets"] = complete_board(rows, now)
        payload["universe"] = 100
        payload["valid"] = 100
        self.live.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.utime(self.live, (now.timestamp(), now.timestamp()))
        return sup.run_once(self.data, self.live, self.status, now=now)

    @staticmethod
    def _events(engine, kind):
        return [e for e in engine["ledger"] if e.get("event_type") == kind]

    def test_board_fresh_but_signal_row_five_minutes_old_writes_no_entry(self):
        rows = [
            _signal_row("SYN0.T", "待機", _row_quote("2026-10-19T10:00:03+09:00")),  # just traded
            _signal_row("SYN1.T", "買いサイン", _row_quote("2026-10-19T09:55:05+09:00")),  # 5 min old
        ]
        engine = self._cycle(rows)
        status = json.loads(self.status.read_text(encoding="utf-8"))
        self.assertEqual(status["quote_freshness"]["state"], "FRESH")  # the board itself is fresh
        self.assertEqual(self._events(engine, "virtual_entry"), [])
        judgment = self._events(engine, "board_judgment")[-1]
        row = [j for j in judgment["judgments"] if j["ticker"] == "SYN1.T"][0]
        self.assertFalse(row["entry_candidate"])
        self.assertEqual(row["row_quote_state"], "STALE")

    def test_undated_future_and_unverified_rows_write_no_entry(self):
        for name, quote in (
            ("undated", _row_quote(None)),
            ("future", _row_quote("2026-10-19T10:03:00+09:00", observed="2026-10-19T10:00:04+09:00")),
            ("assumed_date", _row_quote("2026-10-19T10:00:03+09:00", basis="ASSUMED_TODAY")),
        ):
            with self.subTest(case=name):
                shutil.rmtree(self.data, ignore_errors=True)
                engine = self._cycle([_signal_row("SYN1.T", "買いサイン", quote)])
                self.assertEqual(self._events(engine, "virtual_entry"), [])

    def test_row_from_other_trading_day_blocks_board(self):
        engine = self._cycle([_signal_row("SYN1.T", "買いサイン", _row_quote("2026-10-16T14:59:59+09:00"))])
        status = json.loads(self.status.read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "PAUSED_FAIL_CLOSED")
        self.assertIn("MIXED_SOURCE_DATES", status["quote_freshness"]["reasons"])
        self.assertEqual(self._events(engine, "virtual_entry"), [])

    def test_fresh_signal_row_opens_entry_with_dated_quote(self):
        engine = self._cycle([_signal_row("SYN1.T", "買いサイン", _row_quote("2026-10-19T10:00:04+09:00"))])
        entries = self._events(engine, "virtual_entry")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source_timestamp_at"], "2026-10-19T10:00:04+09:00")
        self.assertIs(entries[0]["real_submit_allowed"], False)
        self.assertIsNone(entries[0]["quantity"])

    def test_exit_is_not_marked_from_a_stale_row_quote(self):
        engine = self._cycle([_signal_row("SYN1.T", "買いサイン", _row_quote("2026-10-19T10:00:04+09:00"))])
        self.assertEqual(len(self._events(engine, "virtual_entry")), 1)

        later = _ts("2026-10-19T10:06:00+09:00")
        identity = dict(IDENTITY_FRESH, source_timestamp="10:05:59", source_timestamp_at="2026-10-19T10:05:59+09:00",
                        source_timestamp_observed_at="2026-10-19T10:05:59+09:00")
        stale_exit = _signal_row("SYN1.T", "待機", _row_quote("2026-10-19T10:00:04+09:00"))
        engine = self._cycle([stale_exit], now=later, identity=identity)
        self.assertEqual(self._events(engine, "virtual_exit"), [])
        self.assertIn("SYN1.T|LONG", engine["open_positions"])

        later2 = _ts("2026-10-19T10:06:02+09:00")
        identity2 = dict(identity, source_timestamp="10:06:01", source_timestamp_at="2026-10-19T10:06:01+09:00",
                         source_timestamp_observed_at="2026-10-19T10:06:01+09:00")
        fresh_exit = _signal_row("SYN1.T", "待機", _row_quote("2026-10-19T10:06:00+09:00"))
        engine = self._cycle([fresh_exit], now=later2, identity=identity2)
        self.assertEqual(len(self._events(engine, "virtual_exit")), 1)
        self.assertNotIn("SYN1.T|LONG", engine["open_positions"])


class RiskGateFreshness(unittest.TestCase):
    def setUp(self):
        self.policy = rg.load_policy()
        self.scenario = {"resolved_status": "CANDIDATE_READY", "symbol": "SYN1.T", "side": "BUY",
                         "horizon": "intraday", "merge_hash": "synthetic-merge-hash", "entry": 1000.0, "stop": 990.0}
        self.kwargs = dict(available_cash_yen=300000, open_positions_count=0, realized_pnl_today_yen=0,
                           regime_risk_multiplier=1.0, estimated_fees_buffer_yen=500, lot_size=100,
                           policy=self.policy)

    def test_stale_quote_blocks_sizing(self):
        stale = _verdict(CASE_BY_NAME["friday_close_republished_monday_0214"])
        got = rg.evaluate_risk(self.scenario, price_freshness=stale, **self.kwargs)
        self.assertEqual(got["decision"], "BLOCK")
        self.assertEqual(got["allowed_qty"], 0)
        self.assertIn("PRICE_NOT_FRESH:STALE_SOURCE_QUOTE", got["block_reasons"])

    def test_shadow_health_disagreement_blocks(self):
        fresh = _verdict(CASE_BY_NAME["normal_fresh_quote"])
        stale = _verdict(CASE_BY_NAME["friday_close_republished_monday_0214"])
        got = rg.evaluate_risk(self.scenario, price_freshness=[fresh, stale], **self.kwargs)
        self.assertEqual(got["decision"], "BLOCK")
        self.assertIn("PRICE_NOT_FRESH:FRESHNESS_VERDICT_MISMATCH", got["block_reasons"])

    def test_empty_and_unknown_evidence_blocks(self):
        unknown = _verdict(CASE_BY_NAME["time_only_date_unknown"])
        for evidence in ([], unknown, [unknown, unknown]):
            with self.subTest(evidence=str(evidence)[:40]):
                got = rg.evaluate_risk(self.scenario, price_freshness=evidence, **self.kwargs)
                self.assertEqual(got["decision"], "BLOCK")

    def test_fresh_agreeing_verdicts_do_not_block_on_freshness(self):
        fresh = _verdict(CASE_BY_NAME["normal_fresh_quote"])
        got = rg.evaluate_risk(self.scenario, price_freshness=[fresh, fresh], **self.kwargs)
        self.assertFalse(any(r.startswith("PRICE_NOT_FRESH") for r in got["block_reasons"]))
        self.assertNotIn("real_submit_allowed", got)


def _windows_powershell():
    # Production runs these scripts in Windows PowerShell 5.1 (powershell.exe).
    # pwsh 7 ConvertFrom-Json turns ISO-8601 strings into DateTime, so a pwsh
    # run would not test the production parser. Parity runs only on 5.1, and
    # the Windows CI job fails if this class is skipped.
    return shutil.which("powershell")


PS_HARNESS = r"""
param([string]$Gateway, [string]$Collector, [string]$Cases)
$ErrorActionPreference = 'Stop'
function Import-Functions([string]$Path, [string[]]$Names) {
    $t = $null; $e = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($Path, [ref]$t, [ref]$e)
    if ($e.Count) { throw "PARSE_FAILED $Path" }
    foreach ($name in $Names) {
        $defs = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true))
        if ($defs.Count -ne 1) { throw "HELPER_MISSING $name" }
        . ([scriptblock]::Create($defs[0].Extent.Text))
        Set-Item -Path ("function:global:" + $name) -Value (Get-Item ("function:" + $name)).ScriptBlock
    }
}
Import-Functions $Gateway @('Get-JstNow','ConvertFrom-OffsetTimestamp','Get-MarketSession','New-QuoteFreshnessVerdict','Get-QuoteFreshness','Get-CombinedQuoteFreshness')
$fixture = [IO.File]::ReadAllText($Cases, [Text.Encoding]::UTF8) | ConvertFrom-Json
$out = [ordered]@{ ps_major = $PSVersionTable.PSVersion.Major; cases = [ordered]@{}; combined = [ordered]@{}; collector = @(); rows = @() }
$byName = @{}
foreach ($case in $fixture.cases) {
    $live = [pscustomobject]@{ live_price_diagnostics = $case.diag; all_targets = @($case.rows) }
    $now = [DateTimeOffset]::Parse($case.now, [Globalization.CultureInfo]::InvariantCulture)
    $v = Get-QuoteFreshness -LiveObj $live -Now $now -PreviousQuoteAt $case.previous_quote_at
    $byName[$case.name] = $v
    $out.cases[$case.name] = $v
}
foreach ($item in $fixture.combined) {
    $b = if ($null -eq $item.b) { $null } else { $byName[$item.b] }
    $out.combined[$item.name] = Get-CombinedQuoteFreshness $byName[$item.a] $b
}
# Collector quote dating: the date comes only from an observed change.
Import-Functions $Collector @('Update-QuoteObservation')
$o = [DateTimeOffset]::Parse('2026-10-19T02:11:40+09:00')
$s1 = Update-QuoteObservation $null '15:30:00' $o
$s2 = Update-QuoteObservation $s1 '15:30:00' $o.AddMinutes(3)
$s3 = Update-QuoteObservation $s2 '09:00:01' ([DateTimeOffset]::Parse('2026-10-19T09:00:02+09:00'))
$s4 = Update-QuoteObservation $s3 '09:00:01' ([DateTimeOffset]::Parse('2026-10-19T09:30:00+09:00'))
$s5 = Update-QuoteObservation $s4 '23:59:59' ([DateTimeOffset]::Parse('2026-10-19T09:30:02+09:00'))
$s6 = Update-QuoteObservation $s5 '' ([DateTimeOffset]::Parse('2026-10-19T09:30:04+09:00'))
$s7 = Update-QuoteObservation $s6 '10:00:01' ([DateTimeOffset]::Parse('2026-10-19T01:00:02+00:00'))
$out.collector = @($s1, $s2, $s3, $s4, $s5, $s6, $s7)
# Per-row dating resets at the JST date change, so rows never mix days.
Import-Functions $Collector @('Get-RowQuoteObservation')
$table = @{}
$r1 = Get-RowQuoteObservation $table 'syn1.t' '14:59:00' ([DateTimeOffset]::Parse('2026-10-16T14:59:30+09:00'))
$r2 = Get-RowQuoteObservation $table 'SYN1.T' '15:00:00' ([DateTimeOffset]::Parse('2026-10-16T15:00:01+09:00'))
$r3 = Get-RowQuoteObservation $table 'SYN1.T' '15:00:00' ([DateTimeOffset]::Parse('2026-10-19T08:59:00+09:00'))
$r4 = Get-RowQuoteObservation $table 'SYN1.T' '09:00:05' ([DateTimeOffset]::Parse('2026-10-19T09:00:06+09:00'))
$out.rows = @($r1, $r2, $r3, $r4)
$out | ConvertTo-Json -Depth 8 -Compress
"""


class PowerShellParity(unittest.TestCase):
    """Gateway /health and Collector quote dating on the same synthetic cases."""

    @classmethod
    def setUpClass(cls):
        exe = _windows_powershell()
        if exe is None:
            raise unittest.SkipTest("Windows PowerShell 5.1 not available; the Windows CI job runs this class")
        tmp = Path(tempfile.mkdtemp(prefix="v10-fresh-ps-"))
        try:
            script = tmp / "harness.ps1"
            script.write_text(PS_HARNESS, encoding="utf-8-sig")
            args = [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                    "-Gateway", str(ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"),
                    "-Collector", str(ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"),
                    "-Cases", str(ROOT / "tests" / "fixtures" / "v10_price_freshness_cases.json")]
            proc = subprocess.run(args, capture_output=True, timeout=120)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            raise AssertionError("PowerShell harness failed: " + stdout[-2000:] +
                                 proc.stderr.decode("utf-8", errors="replace")[-2000:])
        cls.result = json.loads(stdout.splitlines()[-1].lstrip("\ufeff"))

    def test_runs_on_windows_powershell_5(self):
        self.assertEqual(self.result["ps_major"], 5)

    def test_gateway_matches_shared_cases_and_python(self):
        for case in CASES["cases"]:
            with self.subTest(case=case["name"]):
                ps = self.result["cases"][case["name"]]
                py = _verdict(case)
                self.assertEqual(ps["state"], case["expect"]["state"])
                self.assertEqual(sorted(ps["reasons"] or []), sorted(case["expect"]["reasons"]))
                for key in ("state", "fresh", "quote_at", "quote_basis", "market_session",
                            "max_quote_age_seconds", "order_allowed", "real_submit_allowed"):
                    self.assertEqual(ps[key], py[key], key)
                self.assertEqual(sorted(ps["reasons"] or []), py["reasons"])

    def test_gateway_combined_matches_python(self):
        for item in CASES["combined"]:
            with self.subTest(case=item["name"]):
                ps = self.result["combined"][item["name"]]
                self.assertIs(ps["fresh"], item["expect_fresh"])
                self.assertEqual(sorted(ps["reasons"] or []), sorted(item["expect_reasons"]))
                self.assertIs(ps["real_submit_allowed"], False)

    def test_collector_dates_only_observed_changes(self):
        s1, s2, s3, s4, s5, s6, s7 = self.result["collector"]
        # First value after start: no date invented, even if it looks like 15:30.
        self.assertEqual(s1["basis"], "UNOBSERVED_SINCE_START")
        self.assertIsNone(s1["source_timestamp_at"])
        # Same value minutes later is still undated.
        self.assertEqual(s2["basis"], "UNOBSERVED_SINCE_START")
        self.assertIsNone(s2["source_timestamp_at"])
        # A change observed at 09:00:02 dates the quote to that JST day.
        self.assertEqual(s3["basis"], "COLLECTOR_OBSERVED_CHANGE")
        self.assertEqual(s3["source_timestamp_at"], "2026-10-19T09:00:01+09:00")
        self.assertEqual(s3["observed_at"], "2026-10-19T09:00:02+09:00")
        # Unchanged value keeps its original date; its age grows downstream.
        self.assertEqual(s4["source_timestamp_at"], "2026-10-19T09:00:01+09:00")
        # A change to a time later than the observation is not dated.
        self.assertEqual(s5["basis"], "SOURCE_TIME_AFTER_OBSERVATION")
        self.assertIsNone(s5["source_timestamp_at"])
        # Empty value is missing, not dated.
        self.assertEqual(s6["basis"], "SOURCE_TIME_MISSING")
        self.assertIsNone(s6["source_timestamp_at"])
        # Observation clock given in UTC is converted to JST explicitly.
        self.assertEqual(s7["source_timestamp_at"], "2026-10-19T10:00:01+09:00")

    def test_collector_row_dating_resets_at_jst_day_change(self):
        r1, r2, r3, r4 = self.result["rows"]
        self.assertEqual(r1["basis"], "UNOBSERVED_SINCE_START")
        self.assertEqual(r2["source_timestamp_at"], "2026-10-16T15:00:00+09:00")
        # Monday before the first trade: Friday's observation is dropped.
        self.assertIsNone(r3["source_timestamp_at"])
        self.assertEqual(r3["basis"], "UNOBSERVED_SINCE_START")
        self.assertEqual(r4["source_timestamp_at"], "2026-10-19T09:00:05+09:00")


class SourceContracts(unittest.TestCase):
    def test_no_local_timezone_clock_in_supervisor_loop(self):
        text = (ROOT / "scripts" / "ai_shadow_supervisor.py").read_text(encoding="utf-8")
        self.assertNotIn("datetime.now().astimezone()", text)
        self.assertIn("previous_quote_at=previous_quote_at", text)

    def test_collector_publishes_dated_quote_fields(self):
        text = (ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
        for field in ("source_timestamp_at", "source_timestamp_basis", "source_timestamp_observed_at"):
            self.assertIn(field + " = $script:identityQuoteObservation", text)
        self.assertIn("real_submit_allowed = $false", text)
        self.assertNotIn("RssOrder(", text)

    def test_gateway_health_requires_combined_freshness(self):
        text = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Get-CombinedQuoteFreshness $gatewayFreshness $shadowFreshness", text)
        self.assertIn("$runtime.fail_closed = $true", text)
        self.assertIn("$QuoteFreshness = Get-QuoteFreshness -LiveObj $LiveObj", text)


if __name__ == "__main__":
    unittest.main()
