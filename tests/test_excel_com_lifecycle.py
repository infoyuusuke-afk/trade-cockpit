import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / "downloads" / "START_AI_COCKPIT_V6.ps1").read_text(encoding="utf-8-sig")
COLLECTOR = (ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
WATCHER = (ROOT / "ms2_live" / "Kioxia_RSS_Live_Watcher.ps1").read_text(encoding="utf-8-sig")
HEARTBEAT = (ROOT / "ms2_live" / "Kioxia_Safety_Heartbeat.ps1").read_text(encoding="utf-8-sig")


class ExcelComLifecycleContractTests(unittest.TestCase):
    def test_collector_stops_when_workbook_is_closed(self):
        self.assertIn("CollectorWorkbookRotFinder]::FindByIdentity", COLLECTOR)
        self.assertIn("Canonical workbook disappeared from ROT", COLLECTOR)
        self.assertIn("FinalReleaseComObject", COLLECTOR)
        self.assertIn("function Release-CollectorComState", COLLECTOR)
        self.assertIn("Release-CollectorComState", COLLECTOR)
        self.assertNotIn("$excel.Quit()", COLLECTOR)

    def test_watcher_never_reopens_closed_workbook(self):
        self.assertNotIn("Start-Process -FilePath $bookPath", WATCHER)
        self.assertIn("Watcherはブックを自動再起動せず終了します", WATCHER)
        self.assertIn("WatcherはCOM参照を解放して終了します", WATCHER)
        self.assertIn("FinalReleaseComObject", WATCHER)
        self.assertNotIn("$book.Save()\n    Write-Host \"監視を停止しました。Excelは開いたままです。\"", WATCHER)

    def test_heartbeat_releases_every_rot_reference_and_exits_after_close(self):
        self.assertIn("$everAttached = $false", HEARTBEAT)
        self.assertIn("WORKBOOK_CLOSED", HEARTBEAT)
        self.assertIn("Release-ComObjectSafe $dashboard", HEARTBEAT)
        self.assertIn("Release-ComObjectSafe $book", HEARTBEAT)
        self.assertIn("FinalReleaseComObject", HEARTBEAT)
        self.assertNotIn("Start-Process", HEARTBEAT)

    def test_launcher_releases_validation_com_early(self):
        ready = LAUNCHER.index('MarketSpeed II RSS: READY / 285A=')
        release = LAUNCHER.index("Release-ComObjectSafe $rssSheet", ready)
        watcher = LAUNCHER.index('Show-Step 48 "Starting Excel Watcher..."')
        self.assertLess(ready, release)
        self.assertLess(release, watcher)
        self.assertIn("Release-ComObjectSafe $book", LAUNCHER)
        self.assertIn("Release-ComObjectSafe $excel", LAUNCHER)

    def test_launcher_only_quits_zero_workbook_orphan(self):
        self.assertIn("function Close-EmptyExcelApplication", LAUNCHER)
        self.assertIn("$count=[int]$books.Count", LAUNCHER)
        self.assertIn("if($count -eq 0)", LAUNCHER)
        self.assertIn("$app.Quit()", LAUNCHER)
        self.assertNotIn("Stop-Process -Name EXCEL", LAUNCHER)
        self.assertTrue(LAUNCHER.isascii())

    def test_startup_failure_stops_excel_bound_workers_but_keeps_gateway(self):
        self.assertIn("function Stop-ExcelBoundManaged", LAUNCHER)
        stop_block = LAUNCHER[
            LAUNCHER.index("function Stop-ExcelBoundManaged"):
            LAUNCHER.index("function Release-ComObjectSafe")
        ]
        self.assertIn("MS2_RSS_100_Collector", stop_block)
        self.assertIn("Kioxia_Safety_Heartbeat", stop_block)
        self.assertIn("Kioxia_RSS_Live_Watcher", stop_block)
        self.assertNotIn("AI_Cockpit_Local_Gateway", stop_block)
        catch_block = LAUNCHER[LAUNCHER.index("}catch{"):]
        self.assertIn("Stop-ExcelBoundManaged", catch_block)
        self.assertIn("Close-EmptyExcelApplication", catch_block)

    def test_kioxia_live_validation_accepts_canonical_ticker(self):
        self.assertIn('([string]$_.ticker -eq "285A.T")', LAUNCHER)
        self.assertIn("live_quote_valid", LAUNCHER)
        self.assertIn("live_price", LAUNCHER)

    def test_collector_fatal_error_cannot_leave_debug_shell_holding_excel(self):
        collector_launch = [line for line in LAUNCHER.splitlines() if "$Collector" in line and "Start-Process powershell.exe" in line]
        self.assertEqual(len(collector_launch), 1)
        self.assertNotIn("-NoExit", collector_launch[0])
        self.assertIn("trap {", COLLECTOR)
        self.assertIn("Release-CollectorComState", COLLECTOR)
        self.assertIn("exit 1", COLLECTOR)

    def test_screen_updating_is_best_effort_only(self):
        self.assertIn("ScreenUpdating unavailable; continuing.", COLLECTOR)
        self.assertIn('-Retries 1 -Action { $excel.ScreenUpdating = $false }', COLLECTOR)


if __name__ == "__main__":
    unittest.main()
