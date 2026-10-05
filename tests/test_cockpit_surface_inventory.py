import importlib.util
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inventory = _load("cockpit_surface_inventory", "scripts/cockpit_surface_inventory.py")


class CockpitSurfaceInventoryTests(unittest.TestCase):
    def test_every_named_surface_has_one_status(self):
        rows = inventory.inventory()
        found = {item["label"]: item["status"] for item in rows}
        self.assertEqual(found, {
            "Control": "PARTIAL",
            "SCALP 5": "PARTIAL",
            "EVENT 5": "PARTIAL",
            "REALTIME 5": "PARTIAL",
            "キオクシア": "PARTIAL",
            "決算": "PARTIAL",
            "週間振返り": "PARTIAL",
            "保有ポジション": "BLOCKED",
            "実況": "PARTIAL",
            "音声": "PARTIAL",
            "出来高急増": "PARTIAL",
            "予測チャート": "PARTIAL",
            "現在値整合性": "DONE",
            "文字化け": "PARTIAL",
            "AIトレード日記": "PARTIAL",
        })
        self.assertTrue(all(item["status"] in {"DONE", "PARTIAL", "NOT DONE", "BLOCKED"} for item in rows))

    def test_reload_script_parses_and_does_not_stop_the_collector(self):
        script = ROOT / "downloads" / "ACCEPT_SHADOW_LEDGER_RELOAD.ps1"
        text = script.read_text(encoding="utf-8")
        self.assertTrue(text.isascii())
        self.assertNotIn("Excel.Quit", text)
        self.assertNotIn("AI_COCKPIT_CONTROLLER_V9.ps1", text)
        shell = __import__("shutil").which("pwsh") or __import__("shutil").which("powershell")
        if shell is None:
            self.skipTest("PowerShell is not installed")
        proc = subprocess.run(
            [shell, "-NoProfile", "-File", str(script), "-RepoRoot", str(ROOT), "-SelfTest"],
            check=False,
            text=True,
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)
        self.assertIn("SHADOW_LEDGER_RELOAD_SELFTEST PASS", proc.stdout)
        self.assertNotIn("SUPERVISOR_RELOAD_ACCEPTANCE=PASS", proc.stdout)
