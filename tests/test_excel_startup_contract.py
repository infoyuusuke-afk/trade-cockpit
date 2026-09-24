import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / "downloads" / "START_AI_COCKPIT_V6.ps1").read_text(encoding="utf-8-sig")
INSTALLER = (ROOT / "downloads" / "INSTALL_AI_COCKPIT_V6.ps1").read_text(encoding="utf-8-sig")
WATCHER = (ROOT / "ms2_live" / "Kioxia_RSS_Live_Watcher.ps1").read_text(encoding="utf-8-sig")
UPDATE = (ROOT / "scripts" / "update.py").read_text(encoding="utf-8")


class ExcelStartupContractTests(unittest.TestCase):
    def test_launcher_shell_opens_excel_instead_of_com_creating_excel(self):
        self.assertNotIn("New-Object -ComObject Excel.Application", LAUNCHER)
        self.assertIn("Start-Process -FilePath $WorkbookPath", LAUNCHER)
        self.assertIn("CockpitWorkbookRotFinder", LAUNCHER)
        self.assertIn("FindByFullPath", LAUNCHER)

    def test_launcher_verifies_exact_workbook_not_random_active_excel(self):
        self.assertIn("$book=Wait-Workbook $WorkbookPath", LAUNCHER)
        self.assertNotIn('GetActiveObject("Excel.Application")', LAUNCHER)
        self.assertIn("$actualPath=Invoke-ExcelCom", LAUNCHER)

    def test_canonical_workbook_wins_over_fixed(self):
        canonical = LAUNCHER.index("if(Test-Path -LiteralPath $rootCanonical)")
        runtime_canonical = LAUNCHER.index("if(Test-Path -LiteralPath $runtimeCanonical)")
        fixed = LAUNCHER.index("if(Test-Path -LiteralPath $rootFixed)")
        self.assertLess(canonical, fixed)
        self.assertLess(runtime_canonical, fixed)
        self.assertIn("FIXED is recovery-only", LAUNCHER)

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


if __name__ == "__main__":
    unittest.main()
