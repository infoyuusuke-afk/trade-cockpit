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
        self.assertIn('if (-not $brainStopVerified -or -not $workerStopVerified -or -not $script:bridgeStopVerified)',self.stop)
        self.assertLess(self.stop.index('if (-not $brainStopVerified -or -not $workerStopVerified -or -not $script:bridgeStopVerified)'),self.stop.index('Remove-Item -LiteralPath $StateFile -Force'))
    def test_legacy_missing_brain_pid_refused_before_any_controller_stop(self):
        early=self.stop.index('SAFE_STOP_PREFLIGHT=BLOCKED_BRAIN_PID_UNRECORDED')
        controller=self.stop.index('# Stop the supervising RUN/Controller host FIRST.')
        self.assertLess(early,controller)
        self.assertIn('SAFE_STOP_PREFLIGHT=BLOCKED_BRAIN_IDENTITY_UNVERIFIED',self.stop)
        self.assertIn('[int]::TryParse([string]$brainIdentity.Value',self.stop)
        self.assertIn('Test-ExactBrainHandle $beforeBrain $state',self.stop)

    def test_bridge_stop_only_from_verified_parent_and_pinned_handle(self):
        self.assertIn('Get-Process -Id $ExpectedParentId -ErrorAction Stop',self.stop)
        self.assertIn('Get-Process -Id $owner -ErrorAction Stop',self.stop)
        self.assertIn('[int]$childCim.ParentProcessId -ne $ExpectedParentId',self.stop)
        self.assertIn('$child.Kill()',self.stop)
        self.assertIn('$child.WaitForExit(5000)',self.stop)
        self.assertIn('$script:bridgeStopVerified = $false',self.stop)
        self.assertLess(self.stop.index('if (-not $brainStopVerified -or -not $workerStopVerified'),
                        self.stop.index('Remove-Item -LiteralPath $StateFile -Force'))

    def test_preflight_checks_worker_ownership_before_controller_teardown(self):
        first=self.stop.index('# P0-25 verify every recorded worker BEFORE terminating the supervisor.')
        ctrl=self.stop.index('# Stop the supervising RUN/Controller host FIRST.')
        second=self.stop.index('# Every record must belong to the saved session before stopping ANY worker.')
        self.assertLess(first,ctrl)
        self.assertLess(ctrl,second)
        self.assertIn('SAFE_STOP_PREFLIGHT=BLOCKED_FOREIGN_WORKER_PID',self.stop)
        self.assertIn('SAFE_STOP_VERIFY=LISTEN_PORTS_REMAIN',self.stop)
        self.assertIn('SAFE_STOP_VERIFY=TRACKED_PID_STILL_PRESENT',self.stop)
        self.assertLess(self.stop.index('SAFE_STOP_VERIFY=TRACKED_PID_STILL_PRESENT'),
                        self.stop.index('Remove-Item -LiteralPath $StateFile -Force'))

    def test_final_state_is_reread_after_controller_stops(self):
        # Latest BRAIN PID may change while Controller is still supervising.
        controller_stop=self.stop.index("Stop-OwnedJobBridge 28580")
        reread=self.stop.index("$latest = [IO.File]::ReadAllText($StateFile")
        self.assertLess(reread, controller_stop)
        self.assertIn("[int]$latest.controller_pid -ne [int]$state.controller_pid",self.stop)
        self.assertIn("[string]$latest.session_id -cne [string]$state.session_id",self.stop)
        self.assertIn("[int]$latest.brain_observer_pid -le 0",self.stop)
        self.assertIn('Write-Host "Latest BRAIN PID/state unverified after Controller exit; retained state."',self.stop)

    def test_brain_process_handle_is_pinned_for_kill(self):
        section=self.stop.split('if ($field -eq "brain_observer_pid") {',1)[1].split('    if ($null -ne $p -and',1)[0]
        self.assertIn("Test-ExactBrainHandle $p $state",section)
        self.assertIn("$p.Kill()",section)
        self.assertIn("$p.WaitForExit(5000)",section)
        self.assertNotIn("Stop-Process -Id $procId",section)
        self.assertIn("$handle = $Proc.Handle",self.stop)
        self.assertIn("([datetime]$cim.CreationDate).ToUniversalTime()",self.stop)
        for required in ("scripts\\ai_brain_observer.py", "live_ms2.json", "ai_brain_observer_status_v1.json"):
            self.assertIn(required,self.stop)
        self.assertIn("$brainStopVerified = $false",section)

    def test_corrupt_state_and_deletion_error_cannot_report_success(self):
        self.assertIn("ConvertFrom-Json -ErrorAction Stop",self.stop)
        self.assertIn("Controller state missing or invalid",self.stop)
        self.assertIn("Remove-Item -LiteralPath $StateFile -Force -ErrorAction Stop",self.stop)
        self.assertIn("STATE_FILE_STILL_PRESENT",self.stop)
        self.assertIn("V10 state removal failed; cannot report Safe Stop success.",self.stop)

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
