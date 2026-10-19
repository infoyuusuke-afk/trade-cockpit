"""Static fail-closed contracts; runs on both OS, never touches owner runtime."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
PS=ROOT/"downloads"/"V10_WINDOWS_READONLY_ACCEPTANCE.ps1"
CMD=ROOT/"downloads"/"V10_WINDOWS_READONLY_ACCEPTANCE.cmd"

class WindowsReadOnlyAcceptanceContracts(unittest.TestCase):
 def setUp(self):
  self.ps=PS.read_text(encoding="utf-8")
  self.cmd=CMD.read_text(encoding="utf-8")

 def test_only_existing_readonly_verifiers_invoked(self):
  self.assertIn('VERIFY_V10_SOURCE_PIN_READONLY.ps1',self.ps)
  self.assertIn('AI_COCKPIT_V10_BRAIN_PREFLIGHT.ps1',self.ps)
  self.assertIn('V10_APPROVED_SOURCE.json',self.ps)
  self.assertIn('V10_LOCAL_SOURCE_PIN=PASS',self.ps)
  self.assertIn('V10_BRAIN_LOCAL_HEALTH=PASS',self.ps)
  self.assertIn('SOURCE_PIN_BLOCKED',self.ps)
  self.assertIn('V10_BRAIN_HEALTH_BLOCKED',self.ps)
  self.assertIn('V10_REAL_MARKET_AUTHENTICITY=NOT_VERIFIED',self.ps)
  self.assertIn('V10_REAL_TRADING_ACCEPTANCE=NOT_APPROVED',self.ps)
  self.assertIn('OWNER_SOURCE_PIN_INVALID',self.ps)
  self.assertIn('Real_submit_allowed'.upper(),self.ps.upper())

 def test_missing_or_forged_proof_fails_closed(self):
  self.assertIn('Test-ExactProof',self.ps)
  self.assertIn('"REAL_SUBMIT_ALLOWED=1"',self.ps)
  self.assertIn('"UNREVIEWED=1"',self.ps)
  self.assertIn('"TICKER=PRIVATE"',self.ps)
  self.assertIn('if (-not (Test-ExactProof $sourceExit',self.ps)
  self.assertIn('if (-not (Test-ExactProof $brainExit',self.ps)
  self.assertIn('V10_WINDOWS_READONLY_SELFTEST=PASS',self.ps)

 def test_no_mutating_or_order_commands(self):
  import re
  code="\n".join(line for line in self.ps.splitlines()
                 if not line.strip().startswith("#"))
  for pattern in (r"(?im)^\s*(?:Start-Process|Stop-Process|Remove-Item|Move-Item|"
                  r"Copy-Item|Set-Content|Out-File|New-Item|Invoke-RestMethod|"
                  r"Invoke-WebRequest|Start-Job|Register-ScheduledTask)\b",
                  r"(?im)\b(?:git\s+(?:checkout|reset|clean|pull|fetch|push)|"
                  r"submit_order|place_order|real_submit_allowed\s*=\s*\$true)\b"):
   self.assertIsNone(re.search(pattern,code),pattern)
  self.assertNotIn('V10_APPROVED_SOURCE.json" | Set-',self.ps)

 def test_launcher_only_invokes_inspection_and_shows_result(self):
  self.assertIn('V10_WINDOWS_READONLY_ACCEPTANCE.ps1',self.cmd)
  self.assertIn('pause',self.cmd.lower())
  self.assertIn('exit /b %RC%',self.cmd)
  for forbidden in ("START_AI_COCKPIT_V10","RUN_AI_COCKPIT_V10",
                    "STOP_AI_COCKPIT_V10","git pull"):
   self.assertNotIn(forbidden,self.cmd)

 def test_main_only_requires_explicit_owner_release_pin(self):
  self.assertIn('[string]$cfg.branch -cne "main"',self.ps)
  self.assertIn('^[0-9a-fA-F]{40}$',self.ps)
  self.assertIn('OWNER_AUTHENTICATED=0',self.ps)
  self.assertIn('CONTROLLER_STARTED_BY_THIS_CHECK=0',self.ps)

if __name__=="__main__":
 unittest.main()
