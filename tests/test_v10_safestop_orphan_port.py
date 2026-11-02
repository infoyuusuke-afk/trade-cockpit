"""Safe Stop port check (OWNER 2026-11-02): a V10 port left in LISTEN with owner pid 0 (the process already gone) is
waited for up to 2 minutes and is still an abnormal stop if it remains; a port with a living owner keeps the 20 s
wait and is abnormal after it, as before. Nothing is killed. Synthetic only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
STOP = ROOT / "downloads" / "STOP_AI_COCKPIT_V10.ps1"
WINDOWS = os.name == "nt" and shutil.which("powershell")


class OrphanPortWait(unittest.TestCase):
    def setUp(self):
        self.stop = STOP.read_text(encoding="ascii")

    def test_source(self):
        self.assertTrue(all(ord(c) < 128 for c in self.stop))
        loop = self.stop[self.stop.index("function Get-SafeStopListenerVerdict"):self.stop.index("SAFE_STOP_VERIFY=LISTEN_PORTS_REMAIN; retained state.")]
        self.assertIn("$verdict = Get-SafeStopListenerVerdict $listeners ([int]$portWatch.ElapsedMilliseconds)", loop)
        self.assertIn('if ($verdict -ne "wait") { break }', loop)
        self.assertIn("Start-Sleep -Milliseconds 500", loop)
        for banned in ("Stop-Process", "taskkill", ".Kill("):          # nothing is killed while waiting
            self.assertNotIn(banned, loop)
        # still after every component and the Excel were verified stopped, before the state file is removed
        self.assertLess(self.stop.index('Write-SafeStopMarker "stopped_verified"'), self.stop.index("function Get-SafeStopListenerVerdict"))
        self.assertLess(self.stop.index("function Get-SafeStopListenerVerdict"), self.stop.index("Remove-Item -LiteralPath $StateFile -Force"))

    @unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
    def test_verdicts(self):
        cases = [
            ([], 0, "clear"),
            ([0], 0, "wait"), ([0], 19999, "wait"), ([0], 20000, "wait"), ([0, 0], 119999, "wait"), ([0], 120000, "fail"),
            ([1234], 0, "wait"), ([1234], 19999, "wait"), ([1234], 20000, "fail"),
            ([0, 1234], 20000, "fail"),                                   # a living owner among them: 20 s, as before
        ]
        script = (
            "$ast = [System.Management.Automation.Language.Parser]::ParseFile('" + str(STOP) + "', [ref]$null, [ref]$null)\n"
            "$fn = $ast.Find({ param($a) $a -is [System.Management.Automation.Language.FunctionDefinitionAst] -and "
            "$a.Name -eq 'Get-SafeStopListenerVerdict' }, $true)\n"
            ". ([scriptblock]::Create($fn.Extent.Text))\n"
            "$cases = '" + json.dumps(cases) + "' | ConvertFrom-Json\n"
            "foreach ($c in $cases) { $l = @($c[0] | ForEach-Object { [pscustomobject]@{ LocalPort = 28581; OwningProcess = $_ } }); "
            "Write-Output (Get-SafeStopListenerVerdict $l ([int]$c[1])) }\n")
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.stdout.split(), [c[2] for c in cases], out.stderr)


if __name__ == "__main__":
    unittest.main()
