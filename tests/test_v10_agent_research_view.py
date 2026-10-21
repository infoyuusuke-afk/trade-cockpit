"""Specialist AI research view: Gateway route and BRAIN tab (research lane only).

The Brain receiver signs the display view (HMAC-SHA256 with the receiver key
over the exact body_json text). The Gateway re-verifies that signature, the
safety flags and the age of generated_at (300 s) before serving; anything it
cannot verify is UNAVAILABLE with a reason. It is DISABLED when
V10_AGENT_RESEARCH_INBOX is unset. The BRAIN tab behaviour is executed in
v10_agent_research_view.test.mjs. Synthetic only.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"
HTML = (ROOT / "index.html").read_text(encoding="utf-8").replace("\r\n", "\n")
RX_KEY = "a7" * 32
OTHER_KEY = "5e" * 32
NOW = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)

HARNESS = r"""
param([string]$Gateway, [string]$Cases, [string]$Key, [string]$Now)
$ErrorActionPreference = 'Stop'
$t = $null; $e = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Gateway, [ref]$t, [ref]$e)
if ($e.Count) { throw 'PARSE_FAILED' }
$fn = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-AgentResearchView' }, $true))
if ($fn.Count -ne 1) { throw 'FUNCTION_COUNT' }
. ([scriptblock]::Create($fn[0].Extent.Text))
$nowUtc = [DateTimeOffset]::Parse($Now).UtcDateTime
$out = [ordered]@{}
$out.disabled = (Get-AgentResearchView '' $Key $nowUtc)
$out.no_key = (Get-AgentResearchView (Join-Path $Cases 'valid') '' $nowUtc)
$out.relative = (Get-AgentResearchView 'relative\inbox' $Key $nowUtc)
foreach ($dir in Get-ChildItem -LiteralPath $Cases -Directory) { $out[$dir.Name] = (Get-AgentResearchView $dir.FullName $Key $nowUtc) }
$result = [ordered]@{}
foreach ($k in $out.Keys) { $result[$k] = [ordered]@{ status = $out[$k].status; body = $out[$k].body } }
$result | ConvertTo-Json -Depth 4 -Compress
"""


def view(generated_at, **flags):
    v = {"schema_version": "100b-v10-agent-research-display-v1", "generated_at": generated_at.isoformat(),
         "receiver": "v10-brain-agent-research-receiver", "data_lane": "PUBLIC_RESEARCH_UNAUTHENTICATED_NOT_EXECUTION",
         "brain_trade_decision_eligible": False, "live_market_data": False, "real_submit_allowed": False, "runs": []}
    v.update(flags)
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def signed(body, key=RX_KEY):
    return json.dumps({"schema_version": "100b-v10-agent-research-display-signed-v1", "body_json": body,
                       "hmac_sha256": hmac.new(bytes.fromhex(key), body.encode("utf-8"), hashlib.sha256).hexdigest()})


class GatewayAgentResearchRoute(unittest.TestCase):
    def test_route_is_read_only_and_bounded(self):
        text = GATEWAY.read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/agent_research.json') {", text)
        self.assertIn("'agent_research_display_v1.json'", text)
        self.assertIn("GetEnvironmentVariable('AGENT_BRAIN_RECEIVER_HMAC_KEY')", text)
        self.assertIn("[Security.Cryptography.HMACSHA256]::new($keyBytes)", text)
        self.assertNotIn("'agent_research_display_v1.json', ", text.split("$allowedUiFiles = @(")[1].split(")")[0])

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell 5.1 required")
    def test_view_states(self):
        good = view(NOW - timedelta(seconds=10))
        cases = {
            "valid": signed(good),
            "missing": None,
            "tampered": signed(good).replace('"runs\\":[]', '"runs\\":[{}]'),
            "stale": signed(view(NOW - timedelta(minutes=10))),
            "future": signed(view(NOW + timedelta(minutes=5))),
            "wrong_key": signed(good, OTHER_KEY),
            "unsigned_old_format": good,
            "unsafe_flags_resigned": signed(view(NOW - timedelta(seconds=10), real_submit_allowed=True)),
            "broken": "{not json",
        }
        with tempfile.TemporaryDirectory(prefix="v10-agent-view-") as d:
            base = Path(d) / "100億PROJECT" / "cases"
            for name, text in cases.items():
                (base / name).mkdir(parents=True)
                if text is not None:
                    (base / name / "agent_research_display_v1.json").write_text(text, encoding="utf-8")
            # a view written by the real Brain receiver code must verify at the Gateway
            import os
            from contextlib import closing
            from unittest.mock import patch
            from scripts import v10_brain_agent_research_receiver as receiver
            (base / "from_receiver").mkdir()
            with patch.dict(os.environ, {"AGENT_BRIDGE_HMAC_KEY": OTHER_KEY, receiver.RECEIVER_KEY_ENV: RX_KEY}):
                with closing(receiver._connect(base / "from_receiver")) as conn:
                    receiver.write_display(base / "from_receiver", conn, now=NOW - timedelta(seconds=30))
            h = Path(d) / "harness.ps1"
            h.write_text(HARNESS, encoding="utf-8-sig")
            p = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(h),
                                "-Gateway", str(GATEWAY), "-Cases", str(base), "-Key", RX_KEY, "-Now", NOW.isoformat()],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        got = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(got["disabled"]["status"], "200 OK")
        self.assertEqual(json.loads(got["disabled"]["body"])["state"], "DISABLED")
        self.assertEqual(got["valid"]["status"], "200 OK")
        self.assertEqual(got["valid"]["body"], good)
        self.assertEqual(got["from_receiver"]["status"], "200 OK")
        self.assertEqual(json.loads(got["from_receiver"]["body"])["receiver"], "v10-brain-agent-research-receiver")
        expect = {"no_key": "RECEIVER_KEY_UNAVAILABLE", "relative": "INBOX_NOT_ABSOLUTE", "missing": "DISPLAY_MISSING",
                  "tampered": "DISPLAY_SIGNATURE_INVALID", "stale": "DISPLAY_STALE_OR_FUTURE",
                  "future": "DISPLAY_STALE_OR_FUTURE", "wrong_key": "DISPLAY_SIGNATURE_INVALID",
                  "unsigned_old_format": "DISPLAY_WRAPPER_INVALID", "unsafe_flags_resigned": "DISPLAY_FLAGS_INVALID",
                  "broken": "DISPLAY_UNREADABLE"}
        for name, reason in expect.items():
            with self.subTest(case=name):
                self.assertEqual(got[name]["status"], "503 Service Unavailable")
                body = json.loads(got[name]["body"])
                self.assertEqual((body["state"], body["reason"]), ("UNAVAILABLE", reason))
                self.assertIs(body["real_submit_allowed"], False)

    def test_receiver_and_gateway_use_the_same_signature_format(self):
        from scripts import v10_brain_agent_research_receiver as receiver
        text = GATEWAY.read_text(encoding="utf-8-sig")
        self.assertIn(receiver.DISPLAY_WRAPPER_SCHEMA, text)
        self.assertIn(receiver.DISPLAY_SCHEMA, text)
        self.assertIn("$age -gt " + str(receiver.DISPLAY_MAX_AGE_SECONDS), text)


class BrainTabAgentSection(unittest.TestCase):
    def test_section_is_research_only_and_separates_revenue_hunter(self):
        self.assertIn('agentPanel.id="agent-research";', HTML)
        self.assertIn('fetch("/agent_research.json?t="+Date.now())', HTML)
        self.assertIn("売買判定・発注に使いません", HTML)
        self.assertIn("PROJECT進捗（売買判定に使わない）", HTML)
        self.assertIn('x.lane==="PROJECT_PROGRESS_NOT_TRADING"', HTML)
        self.assertIn("AI推論・研究用（MS2の実測データではありません）", HTML)

    @unittest.skipUnless(shutil.which("node"), "node not installed; the CI job runs it")
    def test_view_helpers_in_node(self):
        p = subprocess.run(["node", "--test", str(ROOT / "tests" / "v10_agent_research_view.test.mjs")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout[-6000:] + "\n" + p.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
