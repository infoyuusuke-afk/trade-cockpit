"""OWNER 2026-11-12 「AIコクピットのステータスランプでおれは状況確認はしたい」: the 定時 lamp."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")


class ScheduleLamp(unittest.TestCase):
    def test_gateway_serves_the_check_only_with_safe_flags(self):
        self.assertIn("function Get-ScheduleWatchView([string]$RuntimeDir) {", GW)
        self.assertIn("$file = Join-Path $RuntimeDir 'schedule_watch_v1.json'", GW)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-schedule-watch-v1' -or $view.real_submit_allowed -ne $false", GW)
        self.assertIn("$item.Length -le 2 -or $item.Length -gt 16384", GW)
        self.assertIn("if ($path -eq '/schedule_watch.json') {", GW)

    def test_lamp_sits_with_brain_and_grok(self):
        self.assertIn("<div id='trade-brain-lamp'></div><div id='trade-ai-lamp'></div><div id='trade-sched-lamp'></div>", HTML)

    def test_lamp_colours(self):
        i = HTML.index("const renderSched=()=>{")
        block = HTML[i:HTML.index("setInterval(renderSched,60000);", i)]
        self.assertIn('fetch("/schedule_watch.json?t="+Date.now(),{cache:"no-store"})', block)
        self.assertIn('h==null||h>limit?["gray","定時：点検が古い"', block)
        self.assertIn("limit=offDay?66:26", block)
        self.assertIn('j.state==="STOPPED"?["red","定時：止まりあり"', block)
        self.assertIn('j.state==="LATE"?["yellow","定時：遅れあり"', block)
        self.assertIn('["green","定時：正常"', block)
        self.assertNotIn("innerHTML=\"+", block)


if __name__ == "__main__":
    unittest.main()
