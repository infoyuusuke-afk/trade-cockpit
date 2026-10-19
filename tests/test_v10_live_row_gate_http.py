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
import stat
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
# The synthetic 100-symbol universe written to watchlist_100.json in the
# temporary runtime directory; every payload below carries exactly these rows
# unless a case removes, repeats or replaces one.
UNIVERSE = [IDENTITY] + ["SYN%02d.T" % i for i in range(1, 100)]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sup = _load("v10_shadow_supervisor_row_gate", "scripts/ai_shadow_supervisor.py")
oper = _load("v10_row_gate_operability_helpers", "tests/test_v10_row_gate_operability.py")
market = _load("v10_market_operability_helpers", "tests/test_v10_market_operability.py")


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
        oper.write_watchlist(cls.runtime, UNIVERSE)
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
        # Two Gateways read the same runtime directory. The warm one serves
        # the positive cases and so remembers what it served (regression
        # check). The cold one only ever receives payloads that must be
        # refused, so each negative case is judged without that memory and
        # its own reason (stale, undated, future) is the one reported.
        cls.port = cls._free_port()
        cls._launch([str(GATEWAY), "-RepoRoot", str(ROOT), "-RuntimeDir", str(cls.runtime), "-Port", str(cls.port)], cls.port)
        cls.cold_port = cls._free_port()
        cls._launch([str(GATEWAY), "-RepoRoot", str(ROOT), "-RuntimeDir", str(cls.runtime), "-Port", str(cls.cold_port)], cls.cold_port)
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
    def _launch(cls, args, port):
        process = subprocess.Popen(
            [cls.exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", *args],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(ROOT))
        cls.processes.append(process)
        until = time.monotonic() + 20
        while time.monotonic() < until:
            if process.poll() is not None:
                raise AssertionError(f"Gateway exited early ({process.returncode})")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        raise AssertionError("Gateway failed to bind")

    @classmethod
    def _request(cls, path, port=None):
        port = port or cls.port
        request = (f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n").encode("ascii")
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
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
    def _rows(now, overrides=None, at=None):
        quote_at = at or (now - timedelta(seconds=2))
        rows = [_row(IDENTITY, _quote(quote_at), price=1000.0)]
        for i, ticker in enumerate(UNIVERSE[1:], start=1):
            rows.append(_row(ticker, _quote(quote_at), price=100.0 + i))
        for ticker, row in (overrides or {}).items():
            rows = [row if r["ticker"] == ticker else r for r in rows]
        return rows

    @classmethod
    def _serve(cls, payload, path="/live_ms2.json", port=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        tmp = cls.live.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, cls.live)
        status, body = cls._request(path, port)
        return status, data, body

    def _refuse(self, payload):
        """Send a payload that must be refused to the Gateway with no served history."""
        return self._serve(payload, port=self.cold_port)

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

    def test_stale_row_after_served_history_is_still_refused(self):
        # On the warm Gateway a stale row is also older than what was served,
        # so it is reported as a regression; it is refused either way.
        now = self._now()
        stale = _row("SYN03.T", _quote(now - timedelta(minutes=5)), price=888.75, signal=BUY)
        status, written, body = self._serve(self._payload(rows=self._rows(now, {"SYN03.T": stale}), now=now))
        self._assert_rejected(status, written, body, "ROW_QUOTE_NOT_FRESH", hidden=("888.75", BUY))

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
        status, written, body = self._refuse(self._payload(rows=self._rows(now, {"SYN03.T": stale}), now=now))
        verdict = self._assert_rejected(status, written, body, "ROW_QUOTE_NOT_FRESH", "ROW_STALE_SOURCE_QUOTE",
                                        hidden=("777.25",))
        self.assertEqual(verdict["row_freshness"]["not_fresh_row_count"], 1)
        self.assertEqual(verdict["row_freshness"]["not_fresh_sample"][0]["ticker"], "SYN03.T")
        self.assertTrue(verdict["quote_freshness"]["fresh"])

    def test_row_with_unknown_date_fails_closed(self):
        now = self._now()
        undated = _row("SYN02.T", _quote(None))
        status, written, body = self._refuse(self._payload(rows=self._rows(now, {"SYN02.T": undated}), now=now))
        self._assert_rejected(status, written, body, "ROW_QUOTE_NOT_FRESH", "ROW_SOURCE_DATE_UNKNOWN")

    def test_row_with_missing_time_fails_closed(self):
        now = self._now()
        missing = {"ticker": "SYN04.T", "name": "synthetic", "price": 104.0, "signal": "監視", "data": "LIVE",
                   "source_timestamp": ""}
        status, written, body = self._refuse(self._payload(rows=self._rows(now, {"SYN04.T": missing}), now=now))
        self._assert_rejected(status, written, body, "ROW_QUOTE_NOT_FRESH", "ROW_SOURCE_TIMESTAMP_MISSING")

    def test_row_in_future_fails_closed(self):
        now = self._now()
        future = _row("SYN05.T", _quote(now + timedelta(minutes=5)))
        status, written, body = self._refuse(self._payload(rows=self._rows(now, {"SYN05.T": future}), now=now))
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
        status, written, body = self._refuse(payload)
        self._assert_rejected(status, written, body, "ROW_STALE_SOURCE_QUOTE",
                              hidden=("654.5", "654.0", "640.0", "670.0", "650.5", "初動買い候補"))

    def test_stale_row_with_buy_signal_is_not_a_valid_signal(self):
        now = self._now()
        stale = _row("SYN01.T", _quote(now - timedelta(minutes=5)), price=512.5, signal=BUY, strategy="synthetic",
                     score=95, entry_price=512.0, stop_price=500.0, target1=530.0, target2=545.0)
        status, written, body = self._refuse(self._payload(rows=self._rows(now, {"SYN01.T": stale}), now=now))
        self._assert_rejected(status, written, body, "ROW_STALE_SOURCE_QUOTE",
                              hidden=("512.5", "512.0", "500.0", "530.0", "545.0", BUY))

    def test_identity_stale_fails_whole_response(self):
        now = self._now()
        status, written, body = self._refuse(self._payload(identity_at=now - timedelta(minutes=5), now=now))
        verdict = self._assert_rejected(status, written, body, "STALE_SOURCE_QUOTE")
        self.assertFalse(verdict["quote_freshness"]["fresh"])

    def test_only_file_mtime_new_is_not_fresh(self):
        # updated_at and mtime are seconds old; every quote is 10 minutes old.
        now = self._now()
        old = now - timedelta(minutes=10)
        rows = self._rows(now, at=old)
        status, written, body = self._refuse(self._payload(rows=rows, identity_at=old, now=now))
        self._assert_rejected(status, written, body, "STALE_SOURCE_QUOTE", "ROW_STALE_SOURCE_QUOTE")
        os.utime(self.live, None)
        status, body = self._request("/live_ms2.json", self.cold_port)
        self.assertIn("503", status)
        # The warm Gateway, which has served fresh payloads, refuses it too.
        status, body = self._request("/live_ms2.json")
        self.assertIn("503", status)

    def _shadow_status(self, state, fresh, decision_available=None, omit_availability=False):
        payload = {"state": "RUNNING", "reason": "synthetic", "updated_at": _iso(self._now()),
                   "real_submit_allowed": False,
                   "quote_freshness": {"state": state, "fresh": fresh, "reasons": [] if fresh else ["STALE_SOURCE_QUOTE"],
                                       "real_submit_allowed": False, "order_allowed": False}}
        if not omit_availability:
            payload["board_availability"] = {"decision_available": fresh if decision_available is None else decision_available,
                                             "availability_status": "SYNTHETIC", "real_submit_allowed": False}
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
        self._shadow_status("FRESH", True, decision_available=False)
        runtime = self._health()
        self.assertIs(runtime["quote_freshness_combined"]["fresh"], True)
        self.assertIs(runtime["board_row_freshness"]["fresh"], False)
        self.assertIs(runtime["fail_closed"], True)
        self.assertIn("ROW_STALE_SOURCE_QUOTE", runtime["stale_reason"].split(","))
        # The Collector's own source report stays visible, but /health no
        # longer pairs fail_closed with price_source_status OK or a price.
        self.assertEqual(runtime["source_status"], "OK")
        self.assertNotEqual(runtime["price_source_status"], "OK")
        self.assertIsNone(runtime["live_current_price"])
        self.assertIsNone(runtime["source_timestamp"])
        self.assertIs(runtime["decision_available"], False)
        self.assertEqual(runtime["availability_status"], "BLOCKED_ROW_QUOTES")
        self.assertEqual(runtime["availability"]["state_counts"]["STALE"], 1)
        self.assertEqual(runtime["availability"]["state_counts"]["FRESH"], 99)
        self.assertNotIn("BOARD_AVAILABILITY_MISMATCH", runtime["stale_reason"].split(","))

    # --- P0-V10-ROW-GATE-OPERABILITY-20261019 ---------------------------------

    def _observe(self, port=None):
        status, body = self._request("/observation_ms2.json", port or self.cold_port)
        return status, json.loads(body.decode("utf-8-sig"))

    def _assert_observation_only(self, obs, *hidden):
        for key in ("all_targets", "top5", "hold_top5", "pts_top5", "ir_pts_top5", "kioxia", "market_state",
                    "breadth_pct", "valid"):
            self.assertNotIn(key, obs)
        self.assertEqual(obs["derived_fields"], "WITHHELD")
        self.assertIs(obs["real_submit_allowed"], False)
        self.assertIs(obs["order_allowed"], False)
        text = json.dumps(obs, ensure_ascii=False)
        for needle in ("signal", "entry_price", "stop_price", "target1", "vwap", "score") + hidden:
            self.assertNotIn(needle, text)

    def test_99_fresh_1_stale_keeps_observing_normal_rows(self):
        now = self._now()
        stale = _row("SYN03.T", _quote(now - timedelta(minutes=5)), price=777.25, signal=BUY, entry_price=777.0)
        status, written, body = self._refuse(self._payload(rows=self._rows(now, {"SYN03.T": stale}), now=now))
        self._assert_rejected(status, written, body, "ROW_STALE_SOURCE_QUOTE", hidden=("777.25",))
        status, obs = self._observe()
        self.assertIn("200", status, obs)
        self.assertIs(obs["observation_available"], True)
        self.assertIs(obs["decision_available"], False)
        self.assertEqual(len(obs["rows"]), 100)
        by_ticker = {r["ticker"]: r for r in obs["rows"]}
        self.assertEqual(by_ticker["SYN03.T"]["state"], "STALE")
        self.assertIsNone(by_ticker["SYN03.T"]["observed_price"])
        fresh = [r for r in obs["rows"] if r["state"] == "FRESH"]
        self.assertEqual(len(fresh), 99)
        self.assertTrue(all(r["observed_price"] is not None for r in fresh))
        self.assertEqual(obs["availability"]["state_counts"]["FRESH"], 99)
        self.assertEqual(obs["availability"]["availability_status"], "BLOCKED_ROW_QUOTES")
        self._assert_observation_only(obs, "777.25", BUY)

    def test_90_10_coverage_and_availability_are_reported(self):
        now = self._now()
        old = now - timedelta(minutes=5)
        rows = self._rows(now, {t: _row(t, _quote(old)) for t in UNIVERSE[90:]})
        status, written, body = self._refuse(self._payload(rows=rows, now=now))
        verdict = self._assert_rejected(status, written, body, "ROW_STALE_SOURCE_QUOTE")
        self.assertEqual(verdict["availability"]["state_counts"]["FRESH"], 90)
        self.assertEqual(verdict["availability"]["state_counts"]["STALE"], 10)
        self.assertEqual(verdict["availability"]["fresh_coverage_pct"], 90.0)
        self.assertIs(verdict["availability"]["collector_valid_quality_pass"], True)
        status, obs = self._observe()
        self.assertIn("200", status, obs)
        self.assertEqual(sum(1 for r in obs["rows"] if r["state"] == "FRESH"), 90)
        self.assertEqual(obs["availability"]["fresh_coverage_pct"], 90.0)

    def test_one_of_100_missing_fails_completeness(self):
        now = self._now()
        rows = [r for r in self._rows(now) if r["ticker"] != "SYN42.T"]
        for declared in (99, 100):
            with self.subTest(declared=declared):
                payload = self._payload(rows=rows, now=now, extra={"universe": declared})
                status, written, body = self._refuse(payload)
                verdict = self._assert_rejected(status, written, body, "UNIVERSE_ROW_MISSING", "UNIVERSE_DECLARED_MISMATCH")
                self.assertEqual(verdict["availability"]["missing_count"], 1)
                self.assertEqual(verdict["availability"]["missing_sample"], ["SYN42.T"])
                self.assertEqual(verdict["availability"]["availability_status"], "BLOCKED_UNIVERSE_INCOMPLETE")
                status, obs = self._observe()
                self.assertIn("200", status, obs)
                self.assertEqual(obs["missing_tickers"], ["SYN42.T"])
                # P0-4: the observation lists all 100 expected tickers; the
                # absent one is UNKNOWN with no price or time, never dropped.
                self.assertEqual(len(obs["rows"]), 100)
                absent = [r for r in obs["rows"] if r["ticker"] == "SYN42.T"]
                self.assertEqual(len(absent), 1)
                self.assertEqual(absent[0]["state"], "UNKNOWN")
                self.assertEqual(absent[0]["reasons"], ["ROW_ABSENT_FROM_PAYLOAD"])
                self.assertIsNone(absent[0]["observed_price"])
                self.assertIsNone(absent[0]["quote_at"])
                summary = obs["observation_summary"]
                self.assertEqual((summary["expected_count"], summary["listed_count"]), (100, 100))
                self.assertIs(summary["all_expected_listed"], True)
                self.assertEqual(summary["state_counts"]["FRESH"], 99)
                self.assertEqual(summary["missing_row_count"], 1)
                self.assertEqual(summary["missing_pct"], 1.0)
                self.assertIs(obs["decision_available"], False)

    def test_declared_missing_rows_are_classified_not_dropped(self):
        # P0-5: what the Collector now publishes for a row with no price.
        now = self._now()
        rows = [r for r in self._rows(now) if r["ticker"] not in ("SYN42.T", "SYN43.T")]
        missing = [{"ticker": "SYN42.T", "reason": "PRICE_MISSING", "sheet_code_matches": True,
                    "source_time_text": None, "price": None},
                   {"ticker": "SYN43.T", "reason": "PRICE_MISSING", "sheet_code_matches": False,
                    "source_time_text": "15:00:00", "price": None}]
        payload = self._payload(rows=rows, now=now, extra={"universe": 100, "missing_rows": missing,
                                                           "missing_row_count": 2})
        status, written, body = self._refuse(payload)
        self._assert_rejected(status, written, body, "UNIVERSE_ROW_MISSING")
        status, obs = self._observe()
        self.assertIn("200", status, obs)
        by_ticker = {r["ticker"]: r for r in obs["rows"]}
        self.assertEqual(len(obs["rows"]), 100)
        self.assertEqual((by_ticker["SYN42.T"]["state"], by_ticker["SYN42.T"]["reasons"]), ("UNKNOWN", ["ROW_PRICE_MISSING"]))
        self.assertEqual((by_ticker["SYN43.T"]["state"], by_ticker["SYN43.T"]["reasons"]), ("INVALID", ["ROW_SHEET_CODE_MISMATCH"]))
        for t in ("SYN42.T", "SYN43.T"):
            self.assertIsNone(by_ticker[t]["observed_price"])
            self.assertIsNone(by_ticker[t]["quote_at"])
        summary = obs["observation_summary"]
        self.assertEqual(summary["state_counts"], {"FRESH": 98, "STALE": 0, "UNKNOWN": 1, "INVALID": 1})
        self.assertEqual(summary["missing_row_count"], 2)
        self.assertEqual(summary["fresh_pct"], 98.0)
        self.assertIs(obs["decision_available"], False)
        self.assertNotIn("15:00:00", json.dumps(obs))

    def test_duplicate_ticker_fails_closed(self):
        now = self._now()
        rows = [r for r in self._rows(now) if r["ticker"] != "SYN11.T"] + [_row("SYN12.T", _quote(now - timedelta(seconds=2)))]
        status, written, body = self._refuse(self._payload(rows=rows, now=now, extra={"universe": 100}))
        verdict = self._assert_rejected(status, written, body, "ROW_TICKER_DUPLICATE", "UNIVERSE_ROW_MISSING")
        self.assertEqual(verdict["availability"]["state_counts"]["INVALID"], 1)

    def test_identity_stale_never_serves_the_identity_price(self):
        now = self._now()
        old = now - timedelta(minutes=5)
        rows = self._rows(now, {IDENTITY: _row(IDENTITY, _quote(old), price=1234.5)})
        status, written, body = self._refuse(self._payload(rows=rows, identity_at=old, now=now))
        self._assert_rejected(status, written, body, "STALE_SOURCE_QUOTE", hidden=("1234.5",))
        status, obs = self._observe()
        self.assertIn("200", status, obs)
        identity = [r for r in obs["rows"] if r["ticker"] == IDENTITY][0]
        self.assertEqual(identity["state"], "STALE")
        self.assertIsNone(identity["observed_price"])
        self.assertIs(obs["identity_quote_freshness"]["fresh"], False)
        self._shadow_status("STALE", False)
        runtime = self._health()
        self.assertIsNone(runtime["live_current_price"])
        self.assertNotEqual(runtime["price_source_status"], "OK")
        self.assertEqual(runtime["availability_status"], "BLOCKED_IDENTITY_QUOTE")

    def test_startup_unknown_stays_unknown(self):
        now = self._now()
        rows = [_row(t, _quote(None)) for t in UNIVERSE]
        payload = self._payload(rows=rows, now=now)
        payload["live_price_diagnostics"].update(_quote(None))
        status, written, body = self._refuse(payload)
        self._assert_rejected(status, written, body, "SOURCE_DATE_UNKNOWN", "ROW_SOURCE_DATE_UNKNOWN")
        status, obs = self._observe()
        self.assertIn("200", status, obs)
        self.assertTrue(all(r["state"] in ("UNKNOWN", "INVALID") for r in obs["rows"]))
        self.assertTrue(all(r["observed_price"] is None for r in obs["rows"]))
        self.assertEqual(obs["availability"]["fresh_coverage_pct"], 0.0)

    def test_thin_row_keeps_observation_without_false_live(self):
        for _ in range(3):
            now = self._now()
            thin = _row("SYN99.T", _quote(now - timedelta(minutes=30)), price=55.5)
            status, written, body = self._refuse(self._payload(rows=self._rows(now, {"SYN99.T": thin}), now=now))
            self._assert_rejected(status, written, body, "ROW_STALE_SOURCE_QUOTE", hidden=("55.5",))
            status, obs = self._observe()
            self.assertIn("200", status, obs)
            self.assertEqual([r["ticker"] for r in obs["rows"] if r["state"] != "FRESH"], ["SYN99.T"])

    def test_health_shadow_board_availability_mismatch_fails_closed(self):
        self._serve(self._payload())
        self._shadow_status("FRESH", True, decision_available=False)
        runtime = self._health()
        self.assertIs(runtime["availability"]["decision_available"], True)
        self.assertIn("BOARD_AVAILABILITY_MISMATCH", runtime["stale_reason"].split(","))
        self.assertIs(runtime["fail_closed"], True)
        self.assertIs(runtime["decision_available"], False)
        self.assertEqual(runtime["availability_status"], "BLOCKED_SHADOW_DISAGREES")
        self.assertIsNone(runtime["live_current_price"])
        self._shadow_status("FRESH", True, omit_availability=True)
        runtime = self._health()
        self.assertIn("SHADOW_BOARD_AVAILABILITY_MISSING", runtime["stale_reason"].split(","))
        self.assertIs(runtime["fail_closed"], True)

    def test_recovery_serves_only_the_new_board(self):
        now = self._now()
        stale = _row("SYN08.T", _quote(now - timedelta(minutes=5)))
        status, _, _ = self._serve(self._payload(rows=self._rows(now, {"SYN08.T": stale}), now=now))
        self.assertIn("503", status)
        status, written, body = self._serve(self._payload())
        self.assertIn("200 OK", status, body[:2000])
        self.assertEqual(body, written)

    def test_ui_shows_stopped_for_real_gateway_refusals(self):
        now = self._now()
        stale = _row("SYN03.T", _quote(now - timedelta(minutes=5)), signal=BUY)
        _, _, row_body = self._refuse(self._payload(rows=self._rows(now, {"SYN03.T": stale}), now=now))
        rows = [r for r in self._rows(now) if r["ticker"] != "SYN42.T"]
        _, _, missing_body = self._refuse(self._payload(rows=rows, now=now, extra={"universe": 100}))
        self._shadow_status("FRESH", True, decision_available=False)
        health = json.loads(self._request("/health")[1].decode("utf-8-sig"))
        live = oper.ui_live_body()
        cases = [
            {"name": "row_stale", "bridge_status": 503, "bridge_body": row_body.decode("utf-8-sig"), "health": None},
            {"name": "universe_missing", "bridge_status": 503, "bridge_body": missing_body.decode("utf-8-sig"),
             "health": None},
            {"name": "health_fail_closed", "bridge_status": 200, "bridge_body": json.dumps(live), "health": health},
        ]
        result = oper.run_ui_cases(cases)
        self.assertIsNotNone(result, "node missing on Windows")
        for name, got in result.items():
            with self.subTest(case=name):
                self.assertNotIn("error", got)
                self.assertIs(got["stale"], True)
                self.assertEqual(got["xs_len"], 0)

    def test_restart_restores_served_history_and_detects_regression(self):
        runtime = Path(self.tmp.name) / "restart-runtime"
        runtime.mkdir()
        oper.write_watchlist(runtime, UNIVERSE)
        history = runtime / "v10_gateway_served_quotes.json"
        live = runtime / "live_ms2.json"
        # The synthetic workbook identity is bound to the runtime directory.
        restart_id = _run_powershell(self.exe, ENV_HARNESS, ["-Gateway", str(GATEWAY), "-RuntimeDir", str(runtime)])[
            "workbook_identity_id"]

        def launch():
            port = self._free_port()
            self._launch([str(GATEWAY), "-RepoRoot", str(ROOT), "-RuntimeDir", str(runtime), "-Port", str(port)], port)
            return port, self.processes[-1]

        def serve(port, payload):
            payload["live_price_diagnostics"]["workbook_identity_id"] = restart_id
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            live.write_bytes(data)
            return self._request("/live_ms2.json", port)

        def served_history(port):
            status, body = self._request("/health", port)
            return json.loads(body.decode("utf-8-sig"))["runtime"]["served_history"]

        port, process = launch()
        self.assertEqual(served_history(port)["state"], "NO_HISTORY_FILE")
        self.assertIs(served_history(port)["history_loss_risk"], True)
        now = self._now()
        status, _ = serve(port, self._payload(now=now))
        self.assertIn("200 OK", status)
        self.assertTrue(history.exists())
        self.assertEqual(served_history(port)["state"], "SAVED")
        process.terminate()
        process.wait(timeout=10)

        port, process = launch()
        restored = served_history(port)
        self.assertEqual(restored["state"], "RESTORED")
        self.assertIs(restored["history_loss_risk"], False)
        self.assertEqual(restored["row_count"], 100)
        later = self._now()
        older = self._payload(rows=self._rows(later, at=now - timedelta(seconds=20)), identity_at=now - timedelta(seconds=20),
                              now=later)
        status, body = serve(port, older)
        self.assertIn("503", status)
        reasons = json.loads(body.decode("utf-8-sig"))["stale_reason"].split(",")
        self.assertIn("SOURCE_TIMESTAMP_REGRESSION", reasons)
        self.assertIn("ROW_SOURCE_TIMESTAMP_REGRESSION", reasons)
        process.terminate()
        process.wait(timeout=10)

        history.write_text("{not json", encoding="utf-8")
        port, process = launch()
        self.assertEqual(served_history(port)["state"], "UNREADABLE")
        status, body = serve(port, self._payload())
        self.assertIn("503", status)
        self.assertIn("SERVED_HISTORY_UNREADABLE", json.loads(body.decode("utf-8-sig"))["stale_reason"])
        process.terminate()
        process.wait(timeout=10)


    def test_untraded_identity_is_refused_under_its_own_reason(self):
        # P0-3: what the Collector publishes before the identity's first trade.
        now = self._now()
        payload = self._payload(now=now)
        payload["live_price_diagnostics"].update({
            "price_source_status": "PRICE_SOURCE_MISMATCH", "stale_reason": "IDENTITY_UNTRADED",
            "current_price": None, "symbol": IDENTITY, "data_conflict": True, "live_values_available": False})
        payload.update({"price_source_status": "PRICE_SOURCE_MISMATCH", "stale_reason": "IDENTITY_UNTRADED",
                        "data_conflict": True, "live_values_available": False, "stale": True})
        status, written, body = self._refuse(payload)
        self.assertIn("503", status)
        verdict = json.loads(body.decode("utf-8-sig"))
        reasons = str(verdict["stale_reason"]).split(",")
        self.assertIn("IDENTITY_UNTRADED", reasons)
        self.assertIn("PRICE_SOURCE_MISMATCH", reasons)
        self.assertNotIn("WRONG_SYMBOL_MAPPING", reasons)
        self.assertIsNone(verdict["current_price"])
        self.assertIs(verdict["real_submit_allowed"], False)
        for key in ("all_targets", "top5", "kioxia"):
            self.assertNotIn(key, verdict)
        # A real mapping error is still reported as one.
        payload["live_price_diagnostics"].update({"stale_reason": "WRONG_SYMBOL_MAPPING", "symbol": None})
        payload["stale_reason"] = "WRONG_SYMBOL_MAPPING"
        status, written, body = self._refuse(payload)
        self.assertIn("503", status)
        reasons = str(json.loads(body.decode("utf-8-sig"))["stale_reason"]).split(",")
        self.assertIn("WRONG_SYMBOL_MAPPING", reasons)
        self.assertNotIn("IDENTITY_UNTRADED", reasons)

    def test_excel_com_fail_closed_payload_is_refused(self):
        # P0-2: what the Collector publishes when a loop cannot read Excel.
        payload = market.run_com_harness(self.exe)["fail_closed_payload"]
        payload["updated_at"] = (datetime.now(timezone.utc).replace(tzinfo=None) + self.utc_offset).strftime("%Y-%m-%d %H:%M:%S")
        status, written, body = self._refuse(payload)
        self.assertIn("503", status)
        verdict = json.loads(body.decode("utf-8-sig"))
        reasons = str(verdict["stale_reason"]).split(",")
        self.assertIn("EXCEL_COM_BUSY", reasons)
        self.assertIsNone(verdict["current_price"])
        self.assertIs(verdict["real_submit_allowed"], False)
        self.assertIs(verdict["live_values_available"], False)
        for key in ("all_targets", "top5", "kioxia"):
            self.assertNotIn(key, verdict)
        status, body = self._request("/observation_ms2.json", self.cold_port)
        self.assertIn("503", status)
        self.assertIs(json.loads(body.decode("utf-8-sig"))["observation_available"], False)

    # ---- P0-V10-MARKET-OPERABILITY-20261019 P0-1: verified served history ----
    # Every LIVE (200) response must be on disk first: written atomically,
    # read back and compared. A failed save or readback answers 503 without a
    # price, signal or candidate, and the Gateway keeps the previous history
    # in memory and on disk. Each case uses its own runtime directory and
    # Gateway so no other test's history interferes.

    def _isolated(self, name, *extra_args):
        runtime = Path(self.tmp.name) / name
        runtime.mkdir()
        oper.write_watchlist(runtime, UNIVERSE)
        workbook_id = _run_powershell(self.exe, ENV_HARNESS, ["-Gateway", str(GATEWAY), "-RuntimeDir", str(runtime)])[
            "workbook_identity_id"]
        test = self

        class Isolated:
            history = runtime / "v10_gateway_served_quotes.json"
            live = runtime / "live_ms2.json"

            def launch(self):
                self.port = test._free_port()
                test._launch([str(GATEWAY), "-RepoRoot", str(ROOT), "-RuntimeDir", str(runtime),
                              "-Port", str(self.port), *extra_args], self.port)
                self.process = test.processes[-1]
                return self

            def stop(self):
                self.process.terminate()
                self.process.wait(timeout=10)

            def serve(self, at, port=None):
                now = test._now()
                payload = test._payload(rows=test._rows(now, at=at), identity_at=at, now=now)
                payload["live_price_diagnostics"]["workbook_identity_id"] = workbook_id
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.live.write_bytes(data)
                status, body = test._request("/live_ms2.json", port or self.port)
                return status, data, body

            def health(self, port=None):
                return json.loads(test._request("/health", port or self.port)[1].decode("utf-8-sig"))["runtime"]

            def saved_identity(self):
                return json.loads(self.history.read_text(encoding="utf-8"))["identity_quote_at"]

            def temporaries(self):
                return sorted(p.name for p in runtime.iterdir() if p.name.endswith(".tmp"))

        return Isolated()

    def _assert_history_refusal(self, status, written, body, reason):
        self.assertIn("503", status)
        self.assertNotEqual(body, written)
        verdict = json.loads(body.decode("utf-8-sig"))
        self.assertIn(reason, str(verdict["stale_reason"]).split(","))
        self.assertIs(verdict["real_submit_allowed"], False)
        self.assertIs(verdict["order_allowed"], False)
        self.assertIs(verdict["decision_available"], False)
        self.assertIs(verdict["live_values_available"], False)
        self.assertIsNone(verdict["current_price"])
        for key in ("all_targets", "top5", "hold_top5", "pts_top5", "ir_pts_top5", "kioxia", "market_state",
                    "breadth_pct", "live_price_diagnostics"):
            self.assertNotIn(key, verdict)
        text = body.decode("utf-8-sig")
        for needle in ("SYN", IDENTITY, BUY, "1000.0", "price\":1"):
            self.assertNotIn(needle, text)
        return verdict

    def test_history_saved_and_read_back_before_each_200(self):
        gw = self._isolated("history-ok").launch()
        first = self._now() - timedelta(seconds=20)
        status, written, body = gw.serve(first)
        self.assertIn("200 OK", status, body[:500])
        self.assertEqual(body, written)
        self.assertEqual(gw.saved_identity(), _iso(first))
        # A second LIVE response replaces the existing file. Before this fix the
        # replace call got an empty backup path from PowerShell and failed, the
        # file kept the first time, and the response was still 200.
        second = self._now() - timedelta(seconds=5)
        status, written, body = gw.serve(second)
        self.assertIn("200 OK", status, body[:500])
        self.assertEqual(gw.saved_identity(), _iso(second))
        saved = json.loads(gw.history.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["row_quote_at"]), 100)
        self.assertIs(saved["real_submit_allowed"], False)
        history = gw.health()["served_history"]
        self.assertEqual(history["state"], "SAVED")
        self.assertEqual(history["identity_quote_at"], _iso(second))
        self.assertIsNotNone(history["verified_at"])
        self.assertEqual(history["failure_count"], 0)
        self.assertEqual(gw.temporaries(), [])
        gw.stop()

    def test_history_save_refused_answers_503_and_keeps_previous_history(self):
        gw = self._isolated("history-refused").launch()
        base = self._now() - timedelta(seconds=40)
        status, _, body = gw.serve(base)
        self.assertIn("200 OK", status, body[:500])
        before = gw.history.read_bytes()
        os.chmod(gw.history, stat.S_IREAD)
        try:
            refused_at = self._now() - timedelta(seconds=10)
            status, written, body = gw.serve(refused_at)
            self._assert_history_refusal(status, written, body, "SERVED_HISTORY_SAVE_FAILED")
            # The previous good history is untouched and no temporary is left.
            self.assertEqual(gw.history.read_bytes(), before)
            self.assertEqual(gw.temporaries(), [])
            runtime = gw.health()
            self.assertEqual(runtime["served_history"]["state"], "SAVE_FAILED")
            self.assertEqual(runtime["served_history"]["identity_quote_at"], _iso(base))
            self.assertEqual(runtime["served_history"]["failure_count"], 1)
            self.assertEqual(runtime["served_history"]["last_failure"]["reason"], "SERVED_HISTORY_SAVE_FAILED")
            self.assertIs(runtime["decision_available"], False)
            self.assertIs(runtime["fail_closed"], True)
            self.assertIn("SERVED_HISTORY_SAVE_FAILED", runtime["stale_reason"].split(","))
            # Still refused while the file cannot be written.
            status, written, body = gw.serve(refused_at)
            self._assert_history_refusal(status, written, body, "SERVED_HISTORY_SAVE_FAILED")
        finally:
            os.chmod(gw.history, stat.S_IREAD | stat.S_IWRITE)
        # Recovery needs a new verified save. Memory did not move to the refused
        # time: a quote older than it but newer than the saved one is served.
        between = refused_at - timedelta(seconds=5)
        status, written, body = gw.serve(between)
        self.assertIn("200 OK", status, body[:500])
        self.assertEqual(body, written)
        self.assertEqual(gw.saved_identity(), _iso(between))
        history = gw.health()["served_history"]
        self.assertEqual(history["state"], "SAVED")
        self.assertEqual(history["failure_count"], 2)
        gw.stop()
        # After a restart the restored history is the last verified one, so an
        # older quote is still a regression.
        gw.launch()
        self.assertEqual(gw.health()["served_history"]["identity_quote_at"], _iso(between))
        status, written, body = gw.serve(between - timedelta(seconds=3))
        self.assertIn("503", status)
        self.assertIn("SOURCE_TIMESTAMP_REGRESSION", json.loads(body.decode("utf-8-sig"))["stale_reason"].split(","))
        gw.stop()

    def test_first_save_refused_is_not_live(self):
        gw = self._isolated("history-first-refused").launch()
        gw.history.mkdir()  # a directory where the history file must go
        status, written, body = gw.serve(self._now() - timedelta(seconds=5))
        self._assert_history_refusal(status, written, body, "SERVED_HISTORY_SAVE_FAILED")
        self.assertTrue(gw.history.is_dir())
        self.assertEqual(gw.temporaries(), [])
        self.assertIsNone(gw.health()["served_history"]["identity_quote_at"])
        gw.stop()

    def test_readback_mismatch_answers_503_and_stays_closed(self):
        gw = self._isolated("history-readback", "-ServedHistoryFaultSelfTest", "READBACK_MISMATCH").launch()
        status, written, body = gw.serve(self._now() - timedelta(seconds=5))
        self._assert_history_refusal(status, written, body, "SERVED_HISTORY_READBACK_MISMATCH")
        runtime = gw.health()
        self.assertEqual(runtime["served_history"]["state"], "CONFLICT")
        self.assertIsNone(runtime["served_history"]["identity_quote_at"])
        self.assertIs(runtime["decision_available"], False)
        status, written, body = gw.serve(self._now() - timedelta(seconds=2))
        self._assert_history_refusal(status, written, body, "SERVED_HISTORY_CONFLICT")
        gw.stop()

    def test_history_changed_by_another_writer_is_not_adopted(self):
        gw = self._isolated("history-concurrent").launch()
        base = self._now() - timedelta(seconds=30)
        status, _, body = gw.serve(base)
        self.assertIn("200 OK", status, body[:500])
        # A second Gateway on the same runtime directory restores that history
        # and then serves a newer quote, rewriting the file.
        other = self._isolated_peer(gw)
        status, _, body = gw.serve(base + timedelta(seconds=10), port=other)
        self.assertIn("200 OK", status, body[:500])
        foreign = gw.history.read_bytes()
        status, written, body = gw.serve(base + timedelta(seconds=20))
        self._assert_history_refusal(status, written, body, "SERVED_HISTORY_CONFLICT")
        self.assertEqual(gw.history.read_bytes(), foreign)
        history = gw.health()["served_history"]
        self.assertEqual(history["state"], "CONFLICT")
        self.assertEqual(history["identity_quote_at"], _iso(base))
        # Corrupt bytes written by someone else are refused the same way.
        gw.history.write_text("{not json", encoding="utf-8")
        status, written, body = gw.serve(base + timedelta(seconds=25))
        self._assert_history_refusal(status, written, body, "SERVED_HISTORY_CONFLICT")
        self.assertEqual(gw.history.read_text(encoding="utf-8"), "{not json")
        gw.stop()

    def _isolated_peer(self, gw):
        port = self._free_port()
        self._launch([str(GATEWAY), "-RepoRoot", str(ROOT), "-RuntimeDir", str(gw.history.parent), "-Port", str(port)],
                     port)
        self.assertEqual(gw.health(port)["served_history"]["state"], "RESTORED")
        return port

if __name__ == "__main__":
    unittest.main()
