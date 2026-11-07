"""Weekly analyst scores in the アナリスト tab (OWNER 2026-11-07 「アナリストタブに週間成績の欄を足して…毎週金曜に更新」).
The numbers stay on the OWNER's PC (RuntimeDir/analyst_weekly_v1.json); the repo holds only the code that shows them."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AnalystWeekly(unittest.TestCase):
    def test_gateway_route_and_flags(self):
        gw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/analyst_weekly.json') {", gw)
        fn = gw[gw.index("function Get-AnalystWeeklyView"):]
        fn = fn[:fn.index("\n}\n") if "\n}\n" in fn else fn.index("\r\n}\r\n")]
        self.assertIn("[string]$view.schema_version -cne '100b-v10-analyst-weekly-v1'", fn)
        self.assertIn("$view.real_submit_allowed -ne $false", fn)
        self.assertIn("$view.trade_instruction -ne $false", fn)
        self.assertIn("Join-Path $RuntimeDir 'analyst_weekly_v1.json'", fn)
        self.assertIn("ReparsePoint", fn)

    def test_tab_shows_the_table_only_when_the_flags_are_safe(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('get("/analyst_weekly.json").then(renderWeekly);', html)   # the cards do not wait for it
        self.assertNotIn('await get("/analyst_weekly.json")', html)
        self.assertIn('w.schema_version==="100b-v10-analyst-weekly-v1"&&w.real_submit_allowed===false', html)
        self.assertIn('id="an-weekly"', html)
        self.assertIn("週間成績を読めません", html)     # a missing file shows a plain note
        self.assertIn("検証中", html)
        self.assertIn("<td>'+esc(r.name)+'</td>", html)  # the name is escaped


if __name__ == "__main__":
    unittest.main()
