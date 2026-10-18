"""P0-V10-ACCEPTANCE-FIX-20261019-ROW-GATE: a stale row is never served as LIVE.

Synthetic data only. Before this fix the V10 Gateway checked only the identity
quote (285A.T) and served /live_ms2.json byte-for-byte with HTTP 200, so a
row whose own quote was five minutes old kept its price, its buy signal and
its place in top5 as LIVE information.

The HTTP class launches the REAL Gateway in Windows PowerShell 5.1 on a free
loopback port, writes a synthetic live_ms2.json into a temporary runtime
directory, and checks the actual status code and body of /live_ms2.json and
/health. To reach the freshness gate, the other price-source gates must pass:
a disposable powershell.exe that only sleeps carries the Collector script
name on its command line (Get-ProcessCommandCount), and the payload carries
the synthetic workbook identity for the temporary runtime directory. Nothing
here starts MarketSpeed II, Excel, a real Collector or any order route.

The row parity class runs the Gateway's row functions (AST-extracted from the
same file) and the Shadow supervisor's row_quote_freshness on the same cases.
Both classes need Windows PowerShell 5.1; the Windows CI job fails if they
skip. CI PASS is not a real-machine acceptance and does not approve deploy.
"""
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"
JST = timezone(timedelta(hours=9))
IDENTITY = "285A.T"
WORKBOOK = "Kioxia_MS2_RSS_Live_Signals.xlsx"
BUY = "買いサイン"  # buy signal label used by the Collector


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sup = _load("v10_shadow_supervisor_row_gate", "scripts/ai_shadow_supervisor.py")


def _windows_powershell():
    # pwsh 7 ConvertFrom-Json turns ISO-8601 strings into DateTime, so only
    # Windows PowerShell 5.1 (the production host) tests the real parser.
    if os.name != "nt":
        return None
    return shutil.which("powershell")


def _iso(moment):
    return moment.astimezone(JST).isoformat(timespec="seconds")


def _quote(at, *, basis="COLLECTOR_OBSERVED_CHANGE", observed=None):
    """Row or identity quote fields as the Collector publishes them."""
    if at is None:
        return {"source_timestamp": "09:55:00", "source_timestamp_at": None,
                "source_timestamp_basis": "UNOBSERVED_SINCE_START", "source_timestamp_observed_at": None}
    return {"source_timestamp": at.astimezone(JST).strftime("%H:%M:%S"), "source_timestamp_at": _iso(at),
            "source_timestamp_basis": basis, "source_timestamp_observed_at": _iso(observed or at)}


IMPORT_FUNCTIONS = r"""
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
"""

ENV_HARNESS = r"""
param([string]$Gateway, [string]$RuntimeDir)
$ErrorActionPreference = 'Stop'
""" + IMPORT_FUNCTIONS + r"""
Import-Functions $Gateway @('Get-NormalizedLocalWorkbookPath','Get-WorkbookPublicationId')
$canonical = Join-Path $RuntimeDir 'Kioxia_MS2_RSS_Live_Signals.xlsx'
[ordered]@{
    ps_major = $PSVersionTable.PSVersion.Major
    utc_offset_seconds = [int][TimeZoneInfo]::Local.GetUtcOffset([DateTime]::UtcNow).TotalSeconds
    workbook_identity_id = (Get-WorkbookPublicationId $canonical)
} | ConvertTo-Json -Compress
"""

ROW_HARNESS = r"""
param([string]$Gateway, [string]$Cases)
$ErrorActionPreference = 'Stop'
""" + IMPORT_FUNCTIONS + r"""
Import-Functions $Gateway @('Get-JstNow','ConvertFrom-OffsetTimestamp','Get-MarketSession','New-QuoteFreshnessVerdict','Get-QuoteFreshness','Get-RowQuoteFreshness','Get-BoardRowFreshness')
$fixture = [IO.File]::ReadAllText($Cases, [Text.Encoding]::UTF8) | ConvertFrom-Json
$out = [ordered]@{ ps_major = $PSVersionTable.PSVersion.Major; rows = [ordered]@{}; boards = [ordered]@{} }
foreach ($case in $fixture.rows) {
    $now = [DateTimeOffset]::Parse($case.now, [Globalization.CultureInfo]::InvariantCulture)
    $out.rows[$case.name] = Get-RowQuoteFreshness -Row $case.row -Now $now -BoardQuoteAt $case.board_quote_at
}
foreach ($case in $fixture.boards) {
    $now = [DateTimeOffset]::Parse($case.now, [Globalization.CultureInfo]::InvariantCulture)
    $previous = @{}
    if ($null -ne $case.previous) { foreach ($p in $case.previous.PSObject.Properties) { $previous[$p.Name] = [string]$p.Value } }
    $live = [pscustomobject]@{ all_targets = $case.all_targets }
    $verdict = Get-BoardRowFreshness -LiveObj $live -Now $now -BoardQuoteAt $case.board_quote_at -PreviousRowQuotes $previous
    $out.boards[$case.name] = [ordered]@{ fresh = $verdict.fresh; reasons = @($verdict.reasons); row_count = $verdict.row_count; fresh_row_count = $verdict.fresh_row_count; real_submit_allowed = $verdict.real_submit_allowed; order_allowed = $verdict.order_allowed }
}
$out | ConvertTo-Json -Depth 8 -Compress
"""


def _run_powershell(exe, script_text, args, timeout=120):
    tmp = Path(tempfile.mkdtemp(prefix="v10-rowgate-ps-"))
    try:
        script = tmp / "harness.ps1"
        script.write_text(script_text, encoding="utf-8-sig")
        proc = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(script), *args], capture_output=True, timeout=timeout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        raise AssertionError("PowerShell harness failed: " + stdout[-2000:] +
                             proc.stderr.decode("utf-8", errors="replace")[-2000:])
    return json.loads(stdout.splitlines()[-1].lstrip("﻿"))


BOARD_AT = "2026-10-19T10:00:00+09:00"
NOW = "2026-10-19T10:00:05+09:00"
_T = datetime.fromisoformat(BOARD_AT)
ROW_CASES = [
    ("fresh_same_day", _quote(_T), BOARD_AT, True, []),
    ("five_minutes_old", _quote(_T - timedelta(minutes=5)), BOARD_AT, False, ["STALE_SOURCE_QUOTE"]),
    ("date_unknown", _quote(None), BOARD_AT, False, ["SOURCE_DATE_UNKNOWN"]),
    ("time_missing", {"source_timestamp": "", "source_timestamp_at": None,
                      "source_timestamp_basis": "SOURCE_TIME_MISSING", "source_timestamp_observed_at": None},
     BOARD_AT, False, ["SOURCE_TIMESTAMP_MISSING"]),
    ("fields_absent", {}, BOARD_AT, False, ["SOURCE_TIMESTAMP_MISSING"]),
    ("future", _quote(_T + timedelta(minutes=5)), BOARD_AT, False,
     ["SOURCE_OBSERVATION_IN_FUTURE", "SOURCE_TIMESTAMP_IN_FUTURE"]),
    ("no_offset", {"source_timestamp": "10:00:00", "source_timestamp_at": "2026-10-19T10:00:00",
                   "source_timestamp_basis": "COLLECTOR_OBSERVED_CHANGE",
                   "source_timestamp_observed_at": "2026-10-19T10:00:00+09:00"},
     BOARD_AT, False, ["SOURCE_TIMESTAMP_NO_OFFSET"]),
    ("unverified_basis", _quote(_T, basis="FILE_MTIME"), BOARD_AT, False, ["SOURCE_DATE_BASIS_UNVERIFIED"]),
    ("other_day_than_board", _quote(_T), "2026-10-16T15:00:00+09:00", False, ["MIXED_SOURCE_DATES"]),
    ("board_date_unknown", _quote(_T), None, False, ["BOARD_QUOTE_DATE_UNKNOWN"]),
]


def _row(ticker, quote, **extra):
    row = {"ticker": ticker, "name": "synthetic " + ticker, "price": 100.0, "signal": "監視", "data": "LIVE"}
    row.update(quote)
    row.update(extra)
    return row


BOARD_CASES = [
    ("all_fresh", [_row("SYN01.T", _quote(_T)), _row("SYN02.T", _quote(_T - timedelta(seconds=60)))], None,
     True, []),
    ("one_stale", [_row("SYN01.T", _quote(_T)), _row("SYN02.T", _quote(_T - timedelta(minutes=5)))], None,
     False, ["ROW_QUOTE_NOT_FRESH", "ROW_STALE_SOURCE_QUOTE"]),
    ("one_undated", [_row("SYN01.T", _quote(_T)), _row("SYN02.T", _quote(None))], None,
     False, ["ROW_QUOTE_NOT_FRESH", "ROW_SOURCE_DATE_UNKNOWN"]),
    ("regressed", [_row("SYN01.T", _quote(_T - timedelta(seconds=30)))], {"SYN01.T": BOARD_AT},
     False, ["ROW_QUOTE_NOT_FRESH", "ROW_SOURCE_TIMESTAMP_REGRESSION"]),
    ("empty_board", [], None, False, ["BOARD_ROWS_MISSING", "ROW_QUOTE_NOT_FRESH"]),
    ("ticker_missing", [{"price": 100.0, **_quote(_T)}], None, False, ["ROW_QUOTE_NOT_FRESH", "ROW_TICKER_MISSING"]),
    ("ticker_duplicate", [_row("SYN01.T", _quote(_T)), _row("SYN01.T", _quote(_T))], None,
     False, ["ROW_QUOTE_NOT_FRESH", "ROW_TICKER_DUPLICATE"]),
]


class GatewayRowParity(unittest.TestCase):
    """Gateway Get-RowQuoteFreshness matches Shadow row_quote_freshness."""

    @classmethod
    def setUpClass(cls):
        exe = _windows_powershell()
        if exe is None:
            raise unittest.SkipTest("Windows PowerShell 5.1 not available; the Windows CI job runs this class")
        fixture = {
            "rows": [{"name": n, "row": r, "board_quote_at": b, "now": NOW} for n, r, b, _, _ in ROW_CASES],
            "boards": [{"name": n, "all_targets": rows, "previous": prev, "board_quote_at": BOARD_AT, "now": NOW}
                       for n, rows, prev, _, _ in BOARD_CASES],
        }
        tmp = Path(tempfile.mkdtemp(prefix="v10-rowgate-cases-"))
        try:
            cases = tmp / "cases.json"
            cases.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
            cls.result = _run_powershell(exe, ROW_HARNESS, ["-Gateway", str(GATEWAY), "-Cases", str(cases)])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_runs_on_windows_powershell_5(self):
        self.assertEqual(self.result["ps_major"], 5)

    def test_row_verdicts_match_shadow(self):
        now = datetime.fromisoformat(NOW)
        for name, row, board, fresh, reasons in ROW_CASES:
            with self.subTest(case=name):
                ps = self.result["rows"][name]
                py = sup.row_quote_freshness(row, now=now, board_quote_at=board)
                self.assertIs(ps["fresh"], fresh)
                self.assertEqual(sorted(ps["reasons"] or []), sorted(reasons))
                for key in ("state", "fresh", "quote_at", "order_allowed", "real_submit_allowed"):
                    self.assertEqual(ps[key], py[key], key)
                self.assertEqual(sorted(ps["reasons"] or []), py["reasons"])
                self.assertIs(ps["real_submit_allowed"], False)

    def test_board_verdicts(self):
        for name, rows, _, fresh, reasons in BOARD_CASES:
            with self.subTest(case=name):
                ps = self.result["boards"][name]
                self.assertIs(ps["fresh"], fresh)
                self.assertEqual(sorted(ps["reasons"] or []), sorted(reasons))
                self.assertIs(ps["real_submit_allowed"], False)
                self.assertIs(ps["order_allowed"], False)


FAKE_COLLECTOR_NAME = "MS2_RSS_100_Collector.ps1"


@unittest.skipUnless(os.name == "nt", "Real Gateway listener needs Windows PowerShell 5.1; the Windows CI job runs this class")
class GatewayLiveRowGateHttp(unittest.TestCase):
    """Real Gateway HTTP responses for /live_ms2.json and /health."""

    @classmethod
    def setUpClass(cls):
        cls.exe = _windows_powershell()
        if cls.exe is None:
            raise AssertionError("powershell.exe missing on Windows")
        cls.processes = []
        cls.tmp = tempfile.TemporaryDirectory(prefix="v10-rowgate-http-")
        cls.runtime = Path(cls.tmp.name) / "runtime"
        cls.runtime.mkdir()
        env = _run_powershell(cls.exe, ENV_HARNESS, ["-Gateway", str(GATEWAY), "-RuntimeDir", str(cls.runtime)])
        assert env["ps_major"] == 5, env
        cls.utc_offset = timedelta(seconds=int(env["utc_offset_seconds"]))
        cls.workbook_id = env["workbook_identity_id"]
        assert isinstance(cls.workbook_id, str) and len(cls.workbook_id) == 64, env
        # Disposable stand-in so the Gateway's single-Collector process check
        # passes. It only sleeps; it reads and writes nothing.
        fake_dir = Path(cls.tmp.name) / "fake-process"
        fake_dir.mkdir()
        fake = fake_dir / FAKE_COLLECTOR_NAME
        fake.write_text("Start-Sleep -Seconds 900\n", encoding="utf-8")
        cls.processes.append(subprocess.Popen(
            [cls.exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(fake)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        cls.port = cls._free_port()
        cls._launch([str(GATEWAY), "-RepoRoot", str(ROOT), "-RuntimeDir", str(cls.runtime), "-Port", str(cls.port)])
        cls.live = cls.runtime / "live_ms2.json"
        cls.shadow = cls.runtime / "ai_shadow_status.json"
        # The listener and the stand-in are up; the first all-fresh request
        # proves the harness reaches the freshness gate at all.
        deadline = time.monotonic() + 20
        while True:
            status, _, body = cls._serve(cls._payload())
            if "200" in status or time.monotonic() > deadline:
                break
            time.sleep(0.5)
        cls.warmup = (status, body)

    @classmethod
    def tearDownClass(cls):
        for process in getattr(cls, "processes", []):
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        if hasattr(cls, "tmp"):
            cls.tmp.cleanup()

    @staticmethod
    def _free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    @classmethod
    def _launch(cls, args):
        process = subprocess.Popen(
            [cls.exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", *args],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(ROOT))
        cls.processes.append(process)
        until = time.monotonic() + 20
        while time.monotonic() < until:
            if process.poll() is not None:
                raise AssertionError(f"Gateway exited early ({process.returncode})")
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        raise AssertionError("Gateway failed to bind")

    @classmethod
    def _request(cls, path):
        request = (f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{cls.port}\r\nConnection: close\r\n\r\n").encode("ascii")
        with socket.create_connection(("127.0.0.1", cls.port), timeout=5) as sock:
            sock.settimeout(15)
            sock.sendall(request)
            raw = bytearray()
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                raw.extend(chunk)
        head, _, body = bytes(raw).partition(b"\r\n\r\n")
        return head.split(b"\r\n", 1)[0].decode("ascii", errors="replace"), body

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).astimezone(JST)

    @classmethod
    def _payload(cls, *, rows=None, identity_at=None, now=None, extra=None):
        now = now or cls._now()
        fresh = now - timedelta(seconds=2)
        identity_at = identity_at or fresh
        if rows is None:
            rows = cls._rows(now)
        diag = {
            "symbol": IDENTITY, "current_price": 1000.0, "price_source_status": "OK",
            "source_mode": "MS2_RSS_WORKBOOK", "live_values_available": True, "data_conflict": False,
            "duplicate_collector": False, "duplicate_watcher": False, "stale_reason": "",
            "workbook_identity_verified": True, "workbook_full_name": WORKBOOK,
            "workbook_identity_id": cls.workbook_id,
        }
        diag.update(_quote(identity_at))
        local_now = datetime.now(timezone.utc).replace(tzinfo=None) + cls.utc_offset
        candidates = [r for r in rows if isinstance(r, dict) and r.get("signal") != "監視"] or rows[:1]
        payload = {
            "schema_version": "ms2-common-1.0", "updated_at": local_now.strftime("%Y-%m-%d %H:%M:%S"),
            "observed_at_offset": _iso(now), "timestamp_timezone": "Asia/Tokyo",
            "source": "MarketSpeed II RSS / local PC", "source_mode": "MS2_RSS_WORKBOOK", "universe": len(rows),
            "valid": len(rows), "stale": False, "stale_reason": "", "data_conflict": False,
            "price_source_status": "OK", "live_values_available": True, "real_submit_allowed": False,
            "live_price_diagnostics": diag, "market_state": "synthetic", "breadth_pct": 50.0,
            "kioxia": next((r for r in rows if isinstance(r, dict) and r.get("ticker") == IDENTITY), None),
            "top5": candidates, "hold_top5": [], "pts_top5": [], "ir_pts_top5": [], "all_targets": rows,
        }
        payload.update(extra or {})
        return payload

    @staticmethod
    def _rows(now, overrides=None):
        fresh = now - timedelta(seconds=2)
        rows = [_row(IDENTITY, _quote(fresh), price=1000.0)]
        for i in range(1, 6):
            rows.append(_row(f"SYN0{i}.T", _quote(fresh), price=100.0 + i))
        for ticker, row in (overrides or {}).items():
            rows = [row if r["ticker"] == ticker else r for r in rows]
        return rows

    @classmethod
    def _serve(cls, payload, path="/live_ms2.json"):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        tmp = cls.live.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, cls.live)
        status, body = cls._request(path)
        return status, data, body

    def _assert_rejected(self, status, written, body, *codes, hidden=()):
        self.assertIn("503", status)
        self.assertNotEqual(body, written)
        verdict = json.loads(body.decode("utf-8-sig"))
        reasons = str(verdict.get("stale_reason", "")).split(",")
        for code in codes:
            self.assertIn(code, reasons)
        # The harness itself is not the cause: only freshness fails.
        for unrelated in ("COLLECTOR_PROCESS_UNVERIFIED", "DUPLICATE_PROCESS_CHECK_UNAVAILABLE",
                          "WRONG_SOURCE_WORKBOOK", "CACHED_OR_SAMPLE_PAYLOAD", "STALE_OR_MISSING_TIMESTAMP"):
            self.assertNotIn(unrelated, reasons)
        self.assertIs(verdict["real_submit_allowed"], False)
        self.assertIs(verdict["live_values_available"], False)
        self.assertIsNone(verdict["current_price"])
        for key in ("all_targets", "top5", "hold_top5", "pts_top5", "ir_pts_top5", "kioxia", "market_state", "breadth_pct"):
            self.assertNotIn(key, verdict)
        text = body.decode("utf-8-sig")
        for needle in hidden:
            self.assertNotIn(needle, text)
        # The original file on disk is untouched by the Gateway.
        self.assertEqual(self.live.read_bytes(), written)
        return verdict

    def test_00_harness_reaches_freshness_gate(self):
        status, body = self.warmup
        self.assertIn("200", status, body[:2000])

    def test_all_rows_fresh_serves_original_bytes(self):
        status, written, body = self._serve(self._payload())
        self.assertIn("200 OK", status, body[:2000])
        self.assertEqual(body, written)
        self.assertIs(json.loads(body.decode("utf-8"))["real_submit_allowed"], False)

    def test_identity_fresh_other_row_five_minutes_old_is_not_live(self):
        now = self._now()
        stale = _row("SYN03.T", _quote(now - timedelta(minutes=5)), price=777.25)
        status, written, body = self._serve(self._payload(rows=self._rows(now, {"SYN03.T": stale}), now=now))
        verdict = self._assert_rejected(status, written, body, "ROW_QUOTE_NOT_FRESH", "ROW_STALE_SOURCE_QUOTE",
                                        hidden=("777.25",))
        self.assertEqual(verdict["row_freshness"]["not_fresh_row_count"], 1)
        self.assertEqual(verdict["row_freshness"]["not_fresh_sample"][0]["ticker"], "SYN03.T")
        self.assertTrue(verdict["quote_freshness"]["fresh"])

    def test_row_with_unknown_date_fails_closed(self):
        now = self._now()
        undated = _row("SYN02.T", _quote(None))
        status, written, body = self._serve(self._payload(rows=self._rows(now, {"SYN02.T": undated}), now=now))
        self._assert_rejected(status, written, body, "ROW_QUOTE_NOT_FRESH", "ROW_SOURCE_DATE_UNKNOWN")

    def test_row_with_missing_time_fails_closed(self):
        now = self._now()
        missing = {"ticker": "SYN04.T", "name": "synthetic", "price": 104.0, "signal": "監視", "data": "LIVE",
                   "source_timestamp": ""}
        status, written, body = self._serve(self._payload(rows=self._rows(now, {"SYN04.T": missing}), now=now))
        self._assert_rejected(status, written, body, "ROW_QUOTE_NOT_FRESH", "ROW_SOURCE_TIMESTAMP_MISSING")

    def test_row_in_future_fails_closed(self):
        now = self._now()
        future = _row("SYN05.T", _quote(now + timedelta(minutes=5)))
        status, written, body = self._serve(self._payload(rows=self._rows(now, {"SYN05.T": future}), now=now))
        self._assert_rejected(status, written, body, "ROW_QUOTE_NOT_FRESH", "ROW_SOURCE_TIMESTAMP_IN_FUTURE")

    def test_row_time_regression_fails_closed(self):
        status, written, body = self._serve(self._payload())
        self.assertIn("200 OK", status, body[:2000])
        served_at = json.loads(written)["all_targets"][1]["source_timestamp_at"]
        now = self._now()
        older = _row("SYN01.T", _quote(datetime.fromisoformat(served_at) - timedelta(seconds=20)))
        status, written, body = self._serve(self._payload(rows=self._rows(now, {"SYN01.T": older}), now=now))
        self._assert_rejected(status, written, body, "ROW_QUOTE_NOT_FRESH", "ROW_SOURCE_TIMESTAMP_REGRESSION")

    def test_stale_row_in_top5_is_not_a_live_candidate(self):
        now = self._now()
        stale = _row("SYN02.T", _quote(now - timedelta(minutes=5)), price=654.5, signal="初動買い候補",
                     score=91, entry_price=654.0, stop_price=640.0, target1=670.0, vwap=650.5)
        payload = self._payload(rows=self._rows(now, {"SYN02.T": stale}), now=now)
        self.assertEqual(payload["top5"][0]["ticker"], "SYN02.T")
        status, written, body = self._serve(payload)
        self._assert_rejected(status, written, body, "ROW_STALE_SOURCE_QUOTE",
                              hidden=("654.5", "654.0", "640.0", "670.0", "650.5", "初動買い候補"))

    def test_stale_row_with_buy_signal_is_not_a_valid_signal(self):
        now = self._now()
        stale = _row("SYN01.T", _quote(now - timedelta(minutes=5)), price=512.5, signal=BUY, strategy="synthetic",
                     score=95, entry_price=512.0, stop_price=500.0, target1=530.0, target2=545.0)
        status, written, body = self._serve(self._payload(rows=self._rows(now, {"SYN01.T": stale}), now=now))
        self._assert_rejected(status, written, body, "ROW_STALE_SOURCE_QUOTE",
                              hidden=("512.5", "512.0", "500.0", "530.0", "545.0", BUY))

    def test_identity_stale_fails_whole_response(self):
        now = self._now()
        status, written, body = self._serve(self._payload(identity_at=now - timedelta(minutes=5), now=now))
        verdict = self._assert_rejected(status, written, body, "STALE_SOURCE_QUOTE")
        self.assertFalse(verdict["quote_freshness"]["fresh"])

    def test_only_file_mtime_new_is_not_fresh(self):
        # updated_at and mtime are seconds old; every quote is 10 minutes old.
        now = self._now()
        old = now - timedelta(minutes=10)
        rows = [_row(IDENTITY, _quote(old), price=1000.0)] + [_row(f"SYN0{i}.T", _quote(old)) for i in range(1, 6)]
        status, written, body = self._serve(self._payload(rows=rows, identity_at=old, now=now))
        self._assert_rejected(status, written, body, "STALE_SOURCE_QUOTE", "ROW_STALE_SOURCE_QUOTE")
        os.utime(self.live, None)
        status, body = self._request("/live_ms2.json")
        self.assertIn("503", status)

    def _shadow_status(self, state, fresh):
        payload = {"state": "RUNNING", "reason": "synthetic", "updated_at": _iso(self._now()),
                   "real_submit_allowed": False,
                   "quote_freshness": {"state": state, "fresh": fresh, "reasons": [] if fresh else ["STALE_SOURCE_QUOTE"],
                                       "real_submit_allowed": False, "order_allowed": False}}
        self.shadow.write_text(json.dumps(payload), encoding="utf-8")

    def _health(self):
        status, body = self._request("/health")
        self.assertIn("200", status)
        return json.loads(body.decode("utf-8-sig"))["runtime"]

    def test_health_shadow_gateway_disagreement_fails_closed(self):
        self._serve(self._payload())
        self._shadow_status("FRESH", True)
        agree = self._health()
        self.assertIs(agree["quote_freshness"]["fresh"], True)
        self.assertIs(agree["quote_freshness_combined"]["fresh"], True)
        self.assertIs(agree["board_row_freshness"]["fresh"], True)
        self._shadow_status("STALE", False)
        runtime = self._health()
        self.assertIs(runtime["quote_freshness"]["fresh"], True)
        self.assertIs(runtime["quote_freshness_combined"]["fresh"], False)
        self.assertIn("FRESHNESS_VERDICT_MISMATCH", runtime["quote_freshness_combined"]["reasons"])
        self.assertIs(runtime["fail_closed"], True)
        self.assertIn("FRESHNESS_VERDICT_MISMATCH", runtime["stale_reason"].split(","))

    def test_health_fails_closed_on_stale_row(self):
        now = self._now()
        stale = _row("SYN03.T", _quote(now - timedelta(minutes=5)))
        self._serve(self._payload(rows=self._rows(now, {"SYN03.T": stale}), now=now))
        self._shadow_status("FRESH", True)
        runtime = self._health()
        self.assertIs(runtime["quote_freshness_combined"]["fresh"], True)
        self.assertIs(runtime["board_row_freshness"]["fresh"], False)
        self.assertIs(runtime["fail_closed"], True)
        self.assertIn("ROW_STALE_SOURCE_QUOTE", runtime["stale_reason"].split(","))


if __name__ == "__main__":
    unittest.main()
