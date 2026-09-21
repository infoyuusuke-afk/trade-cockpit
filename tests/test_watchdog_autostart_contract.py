import pathlib,re,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class WatchdogAutostartContract(unittest.TestCase):
 def read(self,n): return (ROOT/"ms2_live"/n).read_text(encoding="utf-8")
 def test_install_is_dry_run_by_default(self):
  s=self.read("Install_External_Watchdog_Autostart.ps1"); self.assertIn("[switch]$Activate",s); self.assertIn("if (-not $Activate)",s); self.assertLess(s.index("if (-not $Activate)"),s.index("Register-ScheduledTask"))
 def test_action_only_calls_hardened_start(self):
  s=self.read("Install_External_Watchdog_Autostart.ps1"); self.assertIn("Start_External_Watchdog.ps1",s); self.assertNotIn("external_watchdog_runner",s)
 def test_idempotent_task_policy(self):
  s=self.read("Install_External_Watchdog_Autostart.ps1"); self.assertIn("-MultipleInstances IgnoreNew",s); self.assertIn("-AtLogOn",s)
 def test_restart_is_bounded(self):
  s=self.read("Install_External_Watchdog_Autostart.ps1"); self.assertIn("-RestartCount 3",s); self.assertIn("New-TimeSpan -Minutes 1",s)
 def test_python_is_resolved_explicitly(self):
  s=self.read("Install_External_Watchdog_Autostart.ps1"); self.assertIn("Get-Command $Python",s); self.assertIn("-Python $quotedPython",s)
 def test_removal_is_dry_run_by_default_and_disables_first(self):
  s=self.read("Remove_External_Watchdog_Autostart.ps1"); self.assertIn("[switch]$Apply",s); self.assertIn("if (-not $Apply)",s); self.assertLess(s.index("Disable-ScheduledTask"),s.index("Unregister-ScheduledTask"))
 def test_no_broker_or_order_commands(self):
  both=(self.read("Install_External_Watchdog_Autostart.ps1")+self.read("Remove_External_Watchdog_Autostart.ps1")).lower()
  for bad in ("marketspeed","rssorder","submit_order","place_order"): self.assertNotIn(bad,both)
