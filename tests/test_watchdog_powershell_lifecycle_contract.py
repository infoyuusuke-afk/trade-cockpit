import pathlib, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class WatchdogPowerShellLifecycleContract(unittest.TestCase):
 def read(self,name): return (ROOT/"ms2_live"/name).read_text(encoding="utf-8")
 def test_start_preflights_python_and_runner(self):
  s=self.read("Start_External_Watchdog.ps1"); self.assertIn("Get-Command $Python",s); self.assertIn("-m scripts.external_watchdog_runner --help",s)
 def test_start_prevents_duplicate_and_identity_mismatch(self):
  s=self.read("Start_External_Watchdog.ps1"); self.assertIn("ALREADY_RUNNING",s); self.assertIn("belongs to another process",s); self.assertIn("Get-CimInstance Win32_Process",s)
 def test_pid_write_is_atomic(self):
  s=self.read("Start_External_Watchdog.ps1"); self.assertIn('$pidTmp=$pidFile+".tmp"',s); self.assertIn("Move-Item -LiteralPath $pidTmp -Destination $pidFile -Force",s)
 def test_start_requires_fresh_output_readiness(self):
  s=self.read("Start_External_Watchdog.ps1"); self.assertIn("LastWriteTimeUtc -gt $beforeOutput",s); self.assertIn("readiness timeout",s); self.assertIn("process exited before readiness",s)
 def test_stop_verifies_identity_before_kill(self):
  s=self.read("Stop_External_Watchdog.ps1"); identity=s.index("identity mismatch"); kill=s.index("Stop-Process -Id $watchdogPid -Force"); self.assertLess(identity,kill); self.assertIn("Get-CimInstance Win32_Process",s)
 def test_stop_cleans_only_missing_process_stale_pid(self):
  s=self.read("Stop_External_Watchdog.ps1"); self.assertIn("stale PID cleaned",s); self.assertIn("stop verification failed",s)
 def test_runtime_is_gitignored(self):
  g=(ROOT/".gitignore").read_text(encoding="utf-8"); self.assertIn("ms2_live/runtime/",g)
