import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / "downloads" / "START_AI_COCKPIT_V6.ps1").read_text(encoding="utf-8-sig")
INSTALLER = (ROOT / "downloads" / "INSTALL_AI_COCKPIT_V6.ps1").read_text(encoding="utf-8-sig")
DIAG = (ROOT / "downloads" / "DIAG_AI_COCKPIT_V6_EXCEL.ps1").read_text(encoding="utf-8-sig")
WATCHER = (ROOT / "ms2_live" / "Kioxia_RSS_Live_Watcher.ps1").read_text(encoding="utf-8-sig")
UPDATE = (ROOT / "scripts" / "update.py").read_text(encoding="utf-8")


class ExcelStartupContractTests(unittest.TestCase):
    def test_launcher_shell_opens_excel_instead_of_com_creating_excel(self):
        self.assertNotIn("New-Object -ComObject Excel.Application", LAUNCHER)
        self.assertIn("Start-Process -FilePath $WorkbookPath", LAUNCHER)
        self.assertIn("CockpitWorkbookRotFinder", LAUNCHER)
        self.assertIn("FindByIdentity", LAUNCHER)

    def test_launcher_verifies_exact_workbook_not_random_active_excel(self):
        self.assertIn("$book=Wait-Workbook $WorkbookPath", LAUNCHER)
        self.assertNotIn('GetActiveObject("Excel.Application")', LAUNCHER)
        self.assertIn("$actualPath=Invoke-ExcelCom", LAUNCHER)
        self.assertIn("nameMatchCount == 1", LAUNCHER)
        self.assertNotIn('GetActiveObject("Excel.Application")', WATCHER)
        self.assertIn("KioxiaWatcherRotFinder", WATCHER)

    def test_canonical_workbook_wins_over_fixed(self):
        canonical = LAUNCHER.index("if(Test-Path -LiteralPath $rootCanonical)")
        root_fixed = LAUNCHER.index("if(Test-Path -LiteralPath $rootFixed)")
        runtime_canonical = LAUNCHER.index("if(Test-Path -LiteralPath $runtimeCanonical)")
        self.assertLess(canonical, root_fixed)
        self.assertLess(root_fixed, runtime_canonical)
        self.assertIn("never overwrite an existing canonical workbook", LAUNCHER)

    def test_watcher_receives_exact_workbook_path(self):
        self.assertIn('param([string]$WorkbookPath = "")', WATCHER)
        self.assertIn('$bookPath = [IO.Path]::GetFullPath($WorkbookPath)', WATCHER)
        self.assertIn('-WorkbookPath "', LAUNCHER)
        self.assertIn("+$WorkbookPath+'", LAUNCHER)

    def test_local_ports_are_unique(self):
        self.assertIn("Test-Port 28580", LAUNCHER)
        self.assertIn("Test-Port 28581", LAUNCHER)
        self.assertIn("Test-Port 28582", LAUNCHER)
        self.assertIn("Start-LocalJsonBridge $watcherJsonPath 28582", WATCHER)
        self.assertNotIn("Start-LocalJsonBridge $watcherJsonPath 28581", WATCHER)
        self.assertIn("http://127.0.0.1:28582/kioxia_watcher_live.json", UPDATE)

    def test_installer_deploys_coherent_runtime_set(self):
        for name in (
            "MS2_RSS_100_Collector.ps1",
            "Kioxia_Safety_Heartbeat.ps1",
            "Kioxia_RSS_Live_Watcher.ps1",
        ):
            self.assertIn(name, INSTALLER)
        self.assertIn("AI_Cockpit_Local_Gateway.ps1", INSTALLER)

    def test_excel_diagnostic_is_installed_and_safe(self):
        self.assertIn("DIAG_AI_COCKPIT_V6_EXCEL.ps1", INSTALLER)
        self.assertIn("AI Cockpit DIAG V6.lnk", INSTALLER)
        self.assertNotIn("New-Object -ComObject Excel.Application", DIAG)
        self.assertNotIn("RssOrder", DIAG)
        self.assertIn("CockpitDiagRot", DIAG)
        self.assertIn("FindByIdentity", DIAG)
        self.assertIn("CountByFileName", DIAG)

    def test_excel_diagnostic_checks_all_local_live_services(self):
        for port in ("28580", "28581", "28582"):
            self.assertIn("Test-Port "+port, DIAG)
        self.assertIn("CollectorFreshness", DIAG)
        self.assertIn("GatewayHealth", DIAG)
        self.assertIn("WatcherFreshness", DIAG)
        self.assertIn("Rss285AProbe", DIAG)
        self.assertIn("excel_startup_diag_", DIAG)

    def test_launcher_and_installer_are_windows_powershell_51_encoding_safe(self):
        self.assertTrue(LAUNCHER.isascii())
        self.assertTrue(INSTALLER.isascii())

    def test_installer_is_windows_powershell_51_safe(self):
        self.assertTrue(INSTALLER.isascii())
        self.assertIn("Save-RemotePowerShellUtf8Bom", INSTALLER)
        self.assertIn("System.Text.UTF8Encoding($true)", INSTALLER)
        self.assertIn("System.Text.UTF8Encoding($false)", INSTALLER)
        self.assertNotIn("Invoke-WebRequest ($base+\"/downloads/START_AI_COCKPIT_V6.ps1\"+$cache) -OutFile $launcher", INSTALLER)
        self.assertIn("Save-RemotePowerShellUtf8Bom ($base+\"/downloads/START_AI_COCKPIT_V6.ps1\"+$cache) $launcher", INSTALLER)
        self.assertIn("Save-RemotePowerShellUtf8Bom ($base+\"/ms2_live/\"+$name+$cache) $tmp", INSTALLER)


if __name__ == "__main__":
    unittest.main()
