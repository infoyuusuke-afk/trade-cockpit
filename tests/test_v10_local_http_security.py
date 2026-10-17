"""Read-only V10 localhost HTTP security checks (no MS2, order or Owner PC)."""
from __future__ import annotations

import contextlib
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


@unittest.skipUnless(os.name == "nt", "Native HTTP negative tests need Windows PowerShell 5.1")
class NativeWindowsHttpAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="v10-http-security-")
        cls.gateway_port = cls._free_port()
        cls.voice_port = cls._free_port()
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


if __name__ == "__main__":
    unittest.main()
