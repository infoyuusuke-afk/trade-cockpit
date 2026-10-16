"""Cross-runtime BRAIN process ownership and no-order regression guard."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller=(ROOT/"downloads/AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")
        cls.gateway=(ROOT/"downloads/AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="ascii")
        cls.engine=(ROOT/"scripts/ai_brain_observer.py").read_text(encoding="utf8")
        cls.ui=(ROOT/"v10_publication_status.js").read_text(encoding="utf8")
    def test_controller_owns_separate_worker_with_private_runtime_paths(self):
        c=self.controller
        self.assertIn('function Start-BrainObserver([string]$RepoRootResolved, [string]$RuntimeDir)',c)
        self.assertIn('$scriptPath = Join-Path $RepoRootResolved "scripts\\ai_brain_observer.py"',c)
        self.assertIn('$statusPath = Join-Path $RuntimeDir "ai_brain_observer_status_v1.json"',c)
        self.assertIn('$brainObserverProc = Start-BrainObserver $RepoRootResolved $RuntimeDir',c)
        self.assertIn('"brain_observer_pid" { "ai_brain_observer.py" }',c)
        self.assertIn('$state.brain_observer_pid = [int]$brainObserverProc.Id',c)
        self.assertIn('Test-OwnedPidIdentity "brain_observer_pid"',c)
    def test_owner_guarded_stop_and_restart_without_wide_process_kill(self):
        c=self.controller
        self.assertIn('"shadow_supervisor_pid", "brain_observer_pid", "controller_pid"',c)
        self.assertIn('"shadow_supervisor_pid", "brain_observer_pid"))',c)
        self.assertIn('Stop-OwnedFromPreviousState',c)
        self.assertIn('Stop-ManagedWorkersOnWorkbookClose',c)
        self.assertIn('$brainObserverRestartAttempts -lt 5',c)
        self.assertIn('$lastBrainObserverRestartAt',c)
    def test_gateway_verifies_source_owner_without_market_promotion(self):
        g=self.gateway
        self.assertIn("Get-V10BrainObserverProof $RuntimeDir $brainExpectedPid $brainProcessVerified",g)
        self.assertIn("Test-HealthProcess $brainExpectedPid 'ai_brain_observer.py'",g)
        self.assertIn("'ai_brain_observer_status_v1.json'",g)
        self.assertIn("BRAIN_UNSAFE_EVIDENCE_CLAIM",g)
        self.assertIn("BRAIN_OBSERVING_PUBLICATION_ONLY",g)
        self.assertIn("brain_publication_state      = 'UNKNOWN_NOT_PUBLISHED'",g)
        self.assertIn("real_submit_allowed        = $false",g)
        self.assertNotIn("$runtime.source_authenticated = $true",g)
    def test_engine_does_not_call_broker_or_mutate_market_input(self):
        s=self.engine
        self.assertIn('"real_submit_allowed": False',s)
        self.assertIn('"source_authenticated": False',s)
        self.assertIn('"cross_source_join_allowed": False',s)
        self.assertIn('"promotion_eligible": False',s)
        self.assertIn('"eligible_observed_n": 0',s)
        self.assertIn('"last_market_data_at": None',s)
        self.assertIn('path.name != "ai_brain_observer_status_v1.json"',s)
        self.assertNotIn("RssOrder",s)
    def test_ui_never_claims_brain_profitability(self):
        s=self.ui
        self.assertIn("brainObserverLabel",s)
        self.assertIn("市場ティックの日付と期待値",s)
        self.assertIn("実注文禁止",s)

if __name__=="__main__":
    unittest.main()
