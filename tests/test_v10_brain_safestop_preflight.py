"""P0 V10 safe stop and read-only pinned preflight invariants."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class PreflightSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stop=(ROOT/"downloads/STOP_AI_COCKPIT_V10.ps1").read_text(encoding="utf-8-sig")
        cls.preflight=(ROOT/"downloads/AI_COCKPIT_V10_BRAIN_PREFLIGHT.ps1").read_text(encoding="utf-8-sig")
    def test_explicit_stop_tracks_independent_brain_pid(self):
        self.assertIn('"brain_observer_pid" { "ai_brain_observer.py" }',self.stop)
        self.assertIn('"sbv2_pid", "shadow_supervisor_pid", "brain_observer_pid"))',self.stop)
        self.assertIn("Test-OwnedPidIdentity $field $procId",self.stop)
        self.assertIn('$brainStopVerified = $true',self.stop)
        self.assertIn('BRAIN observer PID',self.stop)
        self.assertIn('if (-not $brainStopVerified)',self.stop)
        self.assertLess(self.stop.index('if (-not $brainStopVerified)'),self.stop.index('Remove-Item -LiteralPath $StateFile -Force'))
    def test_no_generic_process_kill(self):
        for text in ("Stop-Process -Name","taskkill","Get-Process -Name python"):
            self.assertNotIn(text,self.stop)
    def test_preflight_never_mutates_or_connects_outside_loopback(self):
        for text in ("Start-Process","Stop-Process","Remove-Item","Copy-Item",
                     "Move-Item","git fetch","git reset","git checkout",
                     "RssOrder","api.github.com","curl.exe","PostAsync"):
            self.assertNotIn(text,self.preflight)
        for must in ("PINNED_SHA_BRANCH_REQUIRED","SHA_MISMATCH","BRANCH_MISMATCH",
                     "TRACKED_REPO_DIRTY","BRAIN_SAFE_STOP_NOT_PROVED",
                     "http://127.0.0.1:28581/health","SOURCE_AUTHENTICATED=0",
                     "BRAIN_UNSAFE_PROMOTION","REAL_SUBMIT_ALLOWED=0"):
            self.assertIn(must,self.preflight)
if __name__=="__main__":
    unittest.main()
