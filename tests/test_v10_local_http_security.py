"""Read-only V10 localhost HTTP security checks (no MS2, order or Owner PC)."""
from __future__ import annotations

import contextlib
import json
import hashlib
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"
VOICE = ROOT / "downloads" / "AI_COCKPIT_VOICE_BRIDGE_V10.ps1"
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
WATCHER = ROOT / "ms2_live" / "Kioxia_RSS_Live_Watcher.ps1"


SYNTHETIC_UNIVERSE = ["285A.T"] + ["SYN%02d.T" % i for i in range(1, 100)]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


class SecuritySourceAcceptance(unittest.TestCase):
    def test_no_wildcard_cors_on_any_v10_local_bridge(self):
        for path in (GATEWAY, VOICE, COLLECTOR, WATCHER):
            with self.subTest(path=str(path.relative_to(ROOT))):
                source = read(path)
                self.assertNotIn("Access-Control-Allow-Origin: *", source)
                self.assertIn("V10_HTTP_ORIGIN_BLOCKED", source)
                self.assertIn("sec-fetch-site", source)
                self.assertIn("expectedHost", source)
                self.assertIn("X-Content-Type-Options: nosniff", source)

    def test_only_local_ui_receives_worker_cross_origin_grant(self):
        for path in (VOICE, COLLECTOR, WATCHER):
            with self.subTest(path=str(path.relative_to(ROOT))):
                source = read(path)
                self.assertIn("http://127.0.0.1:28581", source)
                self.assertIn("Access-Control-Allow-Private-Network: true", source)
                self.assertIn("Vary: Origin", source)
        self.assertNotIn("Access-Control-Allow-Private-Network", read(GATEWAY))

    def test_gateway_public_static_paths_fail_closed(self):
        text = read(GATEWAY)
        self.assertIn("V10_PUBLIC_PATH_NOT_ALLOWED", text)
        self.assertIn("V10_REPARSE_PUBLIC_FILE_BLOCKED", text)
        self.assertIn("$allowedUiFiles -cnotcontains $relative", text)
        for sensitive in ("CLAUDE.md", "V10_APPROVED_SOURCE.json", "config.json", ".git/config"):
            self.assertNotIn("'" + sensitive + "'", text)
        for public in (
            "index.html", "voice_client.js", "trade_control.js",
            "credit_supply.json", "event_calendar.json",
            "paper_trade_history.json", "weekly_review.json",
            "earnings_calendar.json", "signals.json", "live_focus.json",
        ):
            self.assertIn("'" + public + "'", text)

    def test_voice_control_and_announce_not_anonymous_browser_side_effects(self):
        text = read(VOICE)
        self.assertIn("V10_VOICE_BROWSER_ORIGIN_REQUIRED", text)
        self.assertIn("V10_VOICE_INTERNAL_CALLER_UNVERIFIED", text)
        self.assertIn("PowerShell", text)
        self.assertIn("'cross-site'", text)
        self.assertIn("$text.Length -gt 1024", text)

    def test_worker_routes_are_explicitly_bounded(self):
        self.assertIn("'/live_ms2.json'", read(COLLECTOR))
        self.assertIn("'/kioxia_watcher_live.json'", read(WATCHER))
        for path in (COLLECTOR, WATCHER):
            self.assertIn("V10_HTTP_ROUTE_BLOCKED", read(path))
            self.assertIn("V10_HTTP_METHOD_BLOCKED", read(path))

    @unittest.skipUnless(os.name == "nt", "PowerShell pure AST helper test")
    def test_sanitized_workbook_identity_matches_both_consumers(self):
        script = r'''param([string]$Source)
$ErrorActionPreference='Stop'
$t=$null; $e=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
if($e.Count){throw 'PARSE_FAILED'}
foreach($name in @('Get-NormalizedLocalWorkbookPath','Get-WorkbookPublicationId','Get-PublishedWorkbookGate')) {
 $defs=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
 if($defs.Count -ne 1){throw 'HELPER_MISSING'}
 . ([scriptblock]::Create($defs[0].Extent.Text))
}
$expected='C:\synthetic\Synthetic.xlsx'
$id=Get-WorkbookPublicationId $expected
if((Get-PublishedWorkbookGate $true $true 'Synthetic.xlsx' $expected '285A.T' $false $id) -ne ''){throw 'VALID_REJECTED'}
foreach($bad in @('',(Get-WorkbookPublicationId 'C:\other\Synthetic.xlsx'))) {
 if((Get-PublishedWorkbookGate $true $true 'Synthetic.xlsx' $expected '285A.T' $true $bad) -notmatch 'WRONG_SOURCE_WORKBOOK'){throw 'WRONG_ID_ALLOWED'}
}
if((Get-PublishedWorkbookGate $true $false 'Synthetic.xlsx' $expected '285A.T' $true $id) -notmatch 'WRONG_SOURCE_WORKBOOK'){throw 'FALSE_IDENTITY_ALLOWED'}
if((Get-PublishedWorkbookGate $true $true 'Synthetic.xlsx' $expected '8035.T' $true $id) -notmatch 'WRONG_SYMBOL_MAPPING'){throw 'WRONG_SYMBOL_ALLOWED'}
'''
        with tempfile.TemporaryDirectory() as tmp:
            wrapper = Path(tmp) / "pure-identity.ps1"
            wrapper.write_text(script, encoding="utf-8")
            for source in (COLLECTOR, GATEWAY):
                result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(wrapper), str(source)], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)



@unittest.skipUnless(os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_OS") == "Windows", "Native listeners run only on disposable hosted Windows CI")
class NativeWindowsHttpAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="v10-http-security-")
        cls.gateway_port = cls._free_port()
        cls.voice_port = cls._free_port()
        cls.collector_port = cls._free_port()
        cls.watcher_port = cls._free_port()
        cls.processes = []
        cls._launch(
            [str(GATEWAY), "-RepoRoot", str(ROOT), "-RuntimeDir", cls.tmp.name,
             "-Port", str(cls.gateway_port)],
            cls.gateway_port,
        )
        cls._launch(
            [str(VOICE), "-Port", str(cls.voice_port),
             "-StatePath", str(Path(cls.tmp.name) / "voice-state.json")],
            cls.voice_port,
        )
        # Run the ACTUAL production Start-Job script-block body in a disposable
        # PowerShell process without starting MarketSpeed II, Excel, or any
        # workbook. The PowerShell AST extracts it from the reviewed file;
        # no HTTP implementation is copied into this test.
        cls.watcher_fixture = Path(cls.tmp.name) / "synthetic-watcher.json"
        cls.watcher_fixture.write_text(json.dumps(cls._watcher_payload()), encoding="utf-8")
        cls._launch_local_worker(
            WATCHER, cls.watcher_port, cls.watcher_fixture
        )
        stocks = {"synthetic %03d" % i: {"ticker": t} for i, t in enumerate(SYNTHETIC_UNIVERSE)}
        (Path(cls.tmp.name) / "watchlist_100.json").write_text(json.dumps({"stocks": stocks}), encoding="utf-8")
        cls.collector_fixture = Path(cls.tmp.name) / "synthetic-collector.json"
        cls._launch_local_worker(COLLECTOR, cls.collector_port, cls.collector_fixture)

    @classmethod
    def _launch_local_worker(cls, source_file: Path, port: int, fixture: Path):
        # Use Parser AST instead of executing the entire Collector/Watcher,
        # which would acquire live Excel/MS2. This runs the same HTTP loop
        # packaged in its Start-Job ScriptBlockExpressionAst.
        wrapper = Path(cls.tmp.name) / ("listener-" + source_file.stem + ".ps1")
        wrapper.write_text(r"""
param(
    [Parameter(Mandatory=$true)][string]$SourceFile,
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$JsonFile,
    [string]$UniverseDir = ""
)
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $SourceFile, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'V10_WORKER_SOURCE_PARSE_FAILED' }
$functions = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Start-LocalJsonBridge'
}, $true))
if ($functions.Count -ne 1) { throw 'V10_WORKER_BRIDGE_IDENTITY_AMBIGUOUS' }
$blocks = @($functions[0].FindAll({
    param($node)
    $node -is [Management.Automation.Language.ScriptBlockExpressionAst] -and
    $node.Extent.Text.Contains('V10_HTTP_ORIGIN_BLOCKED')
}, $true))
if ($blocks.Count -ne 1) { throw 'V10_WORKER_SCRIPTBLOCK_AMBIGUOUS' }
$implementation = $blocks[0].Extent.Text.Trim()
if (-not ($implementation.StartsWith('{') -and $implementation.EndsWith('}'))) {
    throw 'V10_WORKER_SCRIPTBLOCK_INVALID'
}
# Serialize the actual private identity helpers for the extracted Collector job.
# P0-V10-ROW-GATE-OPERABILITY: the Collector job also receives the shared
# quote/row/universe gate functions (Get-WorkbookIdentityInitialization).
foreach ($name in @('Get-NormalizedLocalWorkbookPath','Get-WorkbookPublicationId','Get-PublishedWorkbookGate',
                    'Get-JstNow','ConvertFrom-OffsetTimestamp','Get-MarketSession','New-QuoteFreshnessVerdict',
                    'Get-QuoteFreshness','Get-RowQuoteFreshness','Get-BoardRowFreshness','Get-ExpectedUniverse',
                    'Get-BoardAvailability','Get-AvailabilitySummary')) {
    $defs = @($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name}, $true))
    if ($defs.Count -eq 1) { . ([scriptblock]::Create($defs[0].Extent.Text)) }
}
$loop = [scriptblock]::Create(
    $implementation.Substring(1, $implementation.Length - 2))
# The Collector fixture does not exist: its valid HTTP caller must receive
# 503 fail-closed, never a fabricated real price. The Watcher gets fake JSON.
# Explicit external dependency fake: never inspect host processes or Excel.
# The production listener and its rejection function remain unmodified.
function Get-CimInstance { [pscustomobject]@{CommandLine='MS2_RSS_100_Collector.ps1'} }
& $loop $JsonFile $Port (Join-Path $env:TEMP 'v10-absent-state.json') 'C:\synthetic\Synthetic.xlsx' $UniverseDir
""", encoding="utf-8")
        cls._launch([
            str(wrapper), "-SourceFile", str(source_file),
            "-Port", str(port), "-JsonFile", str(fixture),
            "-UniverseDir", cls.tmp.name,
        ], port)

    @staticmethod
    def _watcher_payload():
        now = datetime.now(timezone(timedelta(hours=9))).replace(microsecond=0)
        return dict(schema_version="kioxia-watcher-1.0",
                    source="Kioxia_RSS_Live_Watcher (Excel RSS)",
                    timestamp_timezone="Asia/Tokyo", updated_at=now.strftime("%Y-%m-%d %H:%M:%S"),
                    observed_at_offset=now.isoformat(), real_submit_allowed=False,
                    price=123.0, signal="SYNTHETIC_ONLY")

    @staticmethod
    def _collector_payload():
        # A complete, freshly dated synthetic 100-row board (the bridge now
        # applies the Gateway's quote, row and universe gate).
        quote_at = datetime.now(timezone(timedelta(hours=9))).replace(microsecond=0) - timedelta(seconds=2)
        quote = dict(source_timestamp=quote_at.strftime("%H:%M:%S"), source_timestamp_at=quote_at.isoformat(),
                     source_timestamp_basis="COLLECTOR_OBSERVED_CHANGE", source_timestamp_observed_at=quote_at.isoformat())
        rows = [dict(ticker=t, price=123.0, data="LIVE", **quote) for t in SYNTHETIC_UNIVERSE]
        return dict(updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    source="MarketSpeed II RSS / local PC", real_submit_allowed=False,
                    universe=100, valid=100, all_targets=rows,
                    live_price_diagnostics=dict(source_mode="MS2_RSS_WORKBOOK",
                    price_source_status="OK", symbol="285A.T", current_price=123.0,
                    live_values_available=True, workbook_identity_verified=True,
                    workbook_full_name="Synthetic.xlsx", workbook_identity_id=hashlib.sha256(r"C:\SYNTHETIC\SYNTHETIC.XLSX".encode()).hexdigest(),
                    **quote))

    def test_watcher_data_freshness_and_lineage_fail_closed(self):
        path = self.watcher_fixture
        mutations = [
            {"source": "cached snapshot"}, {"schema_version": "unknown"},
            {"observed_at_offset": "2020-01-01T09:00:00+09:00", "updated_at": "2020-01-01 09:00:00"},
            {"observed_at_offset": "2099-01-01T09:00:00+09:00"},
            {"observed_at_offset": "2026-10-18 09:00:00"},
            {"updated_at": "invalid"}, {"real_submit_allowed": True},
            {"stale": True}, {"data_conflict": True},
        ]
        try:
            for changes in mutations:
                with self.subTest(changes=changes):
                    payload = self._watcher_payload(); payload.update(changes)
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    status, raw = self._request(self.watcher_port, "/kioxia_watcher_live.json")
                    self.assertIn("503", status)
                    self.assertNotIn(b'"price"', raw)
                    self.assertIn(b'"real_submit_allowed":false', raw)
            for content in ("not json", "null", "{}"):
                path.write_text(content, encoding="utf-8")
                self.assertIn("503", self._request(self.watcher_port, "/")[0])
            path.write_text(json.dumps(self._watcher_payload()), encoding="utf-8")
            os.utime(path, (time.time()-120, time.time()-120))
            self.assertIn("503", self._request(self.watcher_port, "/")[0])
            path.unlink()
            self.assertIn("503", self._request(self.watcher_port, "/")[0])
        finally:
            path.write_text(json.dumps(self._watcher_payload()), encoding="utf-8")
        status, raw = self._request(self.watcher_port, "/")
        self.assertIn("200 OK", status)
        self.assertEqual(json.loads(raw.split(b"\r\n\r\n", 1)[1])["price"], 123.0)

    def test_collector_data_present_and_privacy(self):
        path = self.collector_fixture
        try:
            payload = self._collector_payload()
            path.write_text(json.dumps(payload), encoding="utf-8")
            status, raw = self._request(self.collector_port, "/live_ms2.json", origin="http://127.0.0.1:28581")
            self.assertIn("200 OK", status)
            self.assertNotIn(b"C:", raw)
            self.assertEqual(json.loads(raw.split(b"\r\n\r\n", 1)[1])["live_price_diagnostics"]["current_price"], 123.0)
            for key, value in (("workbook_identity_id", "other-workbook"),
                               ("workbook_identity_verified", False),
                               ("symbol", "8035.T"),
                               ("workbook_full_name", r"C:\Users\PRIVATE_TEST_USER\Synthetic.xlsx")):
                payload = self._collector_payload()
                payload["live_price_diagnostics"][key] = value
                path.write_text(json.dumps(payload), encoding="utf-8")
                status, raw = self._request(self.collector_port, "/")
                self.assertIn("503", status)
                self.assertNotIn(b"PRIVATE_TEST_USER", raw)
                self.assertIsNone(json.loads(raw.split(b"\r\n\r\n", 1)[1])["current_price"])
            payload = self._collector_payload(); payload["updated_at"] = "2000-01-01 00:00:00"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIn("503", self._request(self.collector_port, "/")[0])
        finally:
            path.unlink(missing_ok=True)

    @classmethod
    def tearDownClass(cls):
        for process in getattr(cls, "processes", []):
            with contextlib.suppress(Exception):
                process.terminate()
                process.wait(timeout=5)
            with contextlib.suppress(Exception):
                process.kill()
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
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(ROOT),
        )
        cls.processes.append(process)
        until = time.monotonic() + 18
        while time.monotonic() < until:
            if process.poll() is not None:
                raise AssertionError(f"V10 synthetic listener exited early: {args[0]} ({process.returncode})")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        raise AssertionError(f"V10 synthetic listener failed to bind {port}")

    @staticmethod
    def _request(port, path, *, host=None, origin=None, site=None, agent=None, method="GET"):
        host = f"127.0.0.1:{port}" if host is None else host
        lines = [f"{method} {path} HTTP/1.1", f"Host: {host}", "Connection: close"]
        if origin is not None:
            lines.append("Origin: " + origin)
        if site is not None:
            lines.append("Sec-Fetch-Site: " + site)
        if agent is not None:
            lines.append("User-Agent: " + agent)
        request = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.settimeout(8)
            sock.sendall(request)
            raw = bytearray()
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > 5_000_000:
                    raise AssertionError("response too large")
        self_status = bytes(raw).split(b"\r\n", 1)[0]
        return self_status.decode("ascii", errors="replace"), bytes(raw)

    def test_gateway_allows_approved_ui_and_rejects_private_files(self):
        status, raw = self._request(self.gateway_port, "/index.html")
        self.assertIn("200 OK", status)
        self.assertNotIn(b"Access-Control-Allow-Origin: *", raw)
        for path in ("/CLAUDE.md", "/.git/config", "/downloads/VERIFY_V10_SOURCE_PIN_READONLY.ps1", "/data/private/accounts.json"):
            with self.subTest(path=path):
                status, _ = self._request(self.gateway_port, path)
                self.assertIn("404 Not Found", status)

    def test_gateway_rejects_dns_rebinding_and_cross_site(self):
        for kwargs in (
            {"host": "evil.invalid"},
            {"origin": "https://evil.invalid"},
            {"origin": "null"},
            {"site": "cross-site"},
        ):
            with self.subTest(kwargs=kwargs):
                status, raw = self._request(self.gateway_port, "/health", **kwargs)
                self.assertIn("403 Forbidden", status)
                self.assertNotIn(b"Access-Control-Allow-Origin:", raw)

    def test_gateway_own_origin_and_preflight_behavior(self):
        origin = f"http://127.0.0.1:{self.gateway_port}"
        status, _ = self._request(self.gateway_port, "/index.html", origin=origin, site="same-origin")
        self.assertIn("200 OK", status)
        status, _ = self._request(self.gateway_port, "/health", method="OPTIONS", origin=origin)
        self.assertIn("403 Forbidden", status)

    def test_voice_cross_site_control_rejected_and_ui_control_accepted(self):
        port = self.voice_port
        for kwargs in (
            {},
            {"origin": "https://evil.invalid"},
            {"site": "cross-site"},
            {"host": "evil.invalid"},
        ):
            with self.subTest(kwargs=kwargs):
                status, raw = self._request(port, "/control?enabled=0", **kwargs)
                self.assertIn("403 Forbidden", status)
                self.assertNotIn(b"Access-Control-Allow-Origin: *", raw)
        status, raw = self._request(
            port, "/control?enabled=0",
            origin="http://127.0.0.1:28581", site="same-site"
        )
        self.assertIn("200 OK", status)
        self.assertIn(b'"enabled":false', raw)
        self.assertIn(b"Access-Control-Allow-Origin: http://127.0.0.1:28581", raw)

    def test_voice_external_image_cannot_announce(self):
        status, _ = self._request(
            self.voice_port, "/announce?level=WATCH&text=blocked",
            site="cross-site", agent="Mozilla/5.0"
        )
        self.assertIn("403 Forbidden", status)
        status, _ = self._request(
            self.voice_port, "/announce?level=WATCH&text=blocked",
            agent="Mozilla/5.0"
        )
        self.assertIn("403 Forbidden", status)

    def test_voice_internal_powershell_announcement_compatibility(self):
        # Disable only the isolated synthetic voice instance; no backend audio.
        status, _ = self._request(
            self.voice_port, "/control?enabled=0",
            origin="http://127.0.0.1:28581"
        )
        self.assertIn("200 OK", status)
        status, raw = self._request(
            self.voice_port, "/announce?level=WATCH&text=synthetic",
            agent="Windows PowerShell/5.1"
        )
        self.assertIn("200 OK", status)
        self.assertIn(b'"skipped":true', raw)

    def test_collector_and_watcher_real_listener_cross_site_guards(self):
        for port, path, expected_status in (
            (self.collector_port, "/live_ms2.json", "503 Service Unavailable"),
            (self.watcher_port, "/kioxia_watcher_live.json", "200 OK"),
        ):
            with self.subTest(worker_port=port):
                # The UI is the only browser origin given cross-origin access.
                status, raw = self._request(
                    port, path, origin="http://127.0.0.1:28581", site="same-site")
                self.assertIn(expected_status, status)
                self.assertIn(
                    b"Access-Control-Allow-Origin: http://127.0.0.1:28581", raw)
                self.assertIn(b"Access-Control-Allow-Private-Network: true", raw)
                # Parse the body: Collector emits compact JSON, Watcher
                # emits "key": value with a space. The value must be false.
                body = json.loads(raw.split(b"\r\n\r\n", 1)[1].decode("utf-8"))
                self.assertIs(body.get("real_submit_allowed"), False)

                # No-Origin internal PowerShell request remains compatible.
                status, raw = self._request(port, path, agent="Windows PowerShell/5.1")
                self.assertIn(expected_status, status)
                self.assertNotIn(b"Access-Control-Allow-Origin:", raw)

                for options in (
                    {"host": "attacker.invalid"},
                    {"origin": "https://attacker.invalid"},
                    {"origin": "null"},
                    {"site": "cross-site"},
                    {"origin": "http://127.0.0.1:12345"},
                ):
                    with self.subTest(worker_port=port, attack=options):
                        status, raw = self._request(port, path, **options)
                        self.assertIn("403 Forbidden", status)
                        self.assertNotIn(b"Access-Control-Allow-Origin:", raw)

                for wrong in ("/CLAUDE.md", "/.git/config", "/private/account.json", "/other"):
                    with self.subTest(worker_port=port, wrong_path=wrong):
                        status, _ = self._request(port, wrong)
                        self.assertIn("404 Not Found", status)

                status, _ = self._request(port, path, method="POST")
                self.assertIn("405 Method Not Allowed", status)

                # Denied browser origin never receives the positive PNA headers.
                status, raw = self._request(
                    port, path, method="OPTIONS",
                    origin="https://attacker.invalid", site="cross-site"
                )
                self.assertIn("403 Forbidden", status)
                self.assertNotIn(b"Access-Control-Allow-Private-Network: true", raw)

    def test_gateway_health_omits_private_absolute_checkout_path(self):
        status, raw = self._request(self.gateway_port, "/health")
        self.assertIn("200 OK", status)
        payload = raw.split(b"\r\n\r\n", 1)[1]
        self.assertNotIn(b'"repo_root"', payload)
        self.assertNotIn(str(ROOT).encode("utf-8"), payload)

    def test_gateway_refuses_actual_windows_reparsepoint_static_file(self):
        # Enforce actual filesystem behavior, not mere source-string presence.
        # A private file outside the disposable webroot must never leak
        # through an otherwise whitelisted credit_supply.json path.
        root = Path(self.tmp.name) / "reparse-webroot"
        root.mkdir()
        (root / "index.html").write_text("<html>synthetic</html>", encoding="utf-8")
        target = Path(self.tmp.name) / "PRIVATE_DO_NOT_SERVE.txt"
        marker = "PRIVATE_TEST_TOKEN_NEVER_EXPOSE"
        target.write_text(marker, encoding="utf-8")
        link = root / "credit_supply.json"
        try:
            os.symlink(target, link)
        except OSError as exc:
            self.fail("Windows CI cannot create required symlink test fixture: " + str(exc))
        self.assertTrue(link.is_symlink(), "fixture must be a real symlink/reparse point")
        port = self._free_port()
        self._launch([
            str(GATEWAY), "-RepoRoot", str(root),
            "-RuntimeDir", self.tmp.name, "-Port", str(port)
        ], port)
        status, raw = self._request(port, "/credit_supply.json")
        self.assertIn("403 Forbidden", status)
        self.assertIn(b"V10_REPARSE_PUBLIC_FILE_BLOCKED", raw)
        self.assertNotIn(marker.encode("utf-8"), raw)


if __name__ == "__main__":
    unittest.main()
