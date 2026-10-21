"""Specialist AI research view: Gateway route and BRAIN tab (research lane only).

The Gateway re-reads agent_research_display_v1.json from the private inbox,
checks size, link and safety flags, and serves it read-only; it is DISABLED
when V10_AGENT_RESEARCH_INBOX is unset. The BRAIN tab behaviour is executed
in v10_agent_research_view.test.mjs. Synthetic only.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"
HTML = (ROOT / "index.html").read_text(encoding="utf-8").replace("\r\n", "\n")

HARNESS = r"""
param([string]$Gateway, [string]$Inbox)
$ErrorActionPreference = 'Stop'
$t = $null; $e = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Gateway, [ref]$t, [ref]$e)
if ($e.Count) { throw 'PARSE_FAILED' }
$fn = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-AgentResearchView' }, $true))
if ($fn.Count -ne 1) { throw 'FUNCTION_COUNT' }
. ([scriptblock]::Create($fn[0].Extent.Text))
$out = [ordered]@{}
$out.disabled = (Get-AgentResearchView '').status
$out.missing = (Get-AgentResearchView $Inbox).status
$file = Join-Path $Inbox 'agent_research_display_v1.json'
$ok = '{"schema_version":"100b-v10-agent-research-display-v1","real_submit_allowed":false,"brain_trade_decision_eligible":false,"live_market_data":false,"runs":[]}'
[IO.File]::WriteAllText($file, $ok)
$v = Get-AgentResearchView $Inbox
$out.valid = $v.status
$out.valid_body_same = ($v.body -eq $ok)
[IO.File]::WriteAllText($file, $ok.Replace('"real_submit_allowed":false', '"real_submit_allowed":true'))
$out.unsafe = (Get-AgentResearchView $Inbox).status
[IO.File]::WriteAllText($file, '{not json')
$out.broken = (Get-AgentResearchView $Inbox).status
$out.relative = (Get-AgentResearchView 'relative\inbox').status
$out | ConvertTo-Json -Compress
"""


class GatewayAgentResearchRoute(unittest.TestCase):
    def test_route_is_read_only_and_bounded(self):
        text = GATEWAY.read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/agent_research.json') {", text)
        self.assertIn("'agent_research_display_v1.json'", text)
        self.assertIn("$item.Length -gt 262144", text)
        self.assertNotIn("'agent_research_display_v1.json', ", text.split("$allowedUiFiles = @(")[1].split(")")[0])

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell 5.1 required")
    def test_view_states(self):
        with tempfile.TemporaryDirectory(prefix="v10-agent-view-") as d:
            inbox = Path(d) / "100億PROJECT" / "受け箱"
            inbox.mkdir(parents=True)
            h = Path(d) / "harness.ps1"
            h.write_text(HARNESS, encoding="utf-8-sig")
            p = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(h),
                                "-Gateway", str(GATEWAY), "-Inbox", str(inbox)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        got = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(got["disabled"], "200 OK")
        self.assertEqual(got["missing"], "503 Service Unavailable")
        self.assertEqual(got["valid"], "200 OK")
        self.assertIs(got["valid_body_same"], True)
        self.assertEqual(got["unsafe"], "503 Service Unavailable")
        self.assertEqual(got["broken"], "503 Service Unavailable")
        self.assertEqual(got["relative"], "503 Service Unavailable")


class BrainTabAgentSection(unittest.TestCase):
    def test_section_is_research_only_and_separates_revenue_hunter(self):
        self.assertIn('agentPanel.id="agent-research";', HTML)
        self.assertIn('fetch("/agent_research.json?t="+Date.now())', HTML)
        self.assertIn("売買判定・発注に使いません", HTML)
        self.assertIn("PROJECT進捗（売買判定に使わない）", HTML)
        self.assertIn('x.lane==="PROJECT_PROGRESS_NOT_TRADING"', HTML)

    @unittest.skipUnless(shutil.which("node"), "node not installed; the CI job runs it")
    def test_view_helpers_in_node(self):
        p = subprocess.run(["node", "--test", str(ROOT / "tests" / "v10_agent_research_view.test.mjs")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout[-6000:] + "\n" + p.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
