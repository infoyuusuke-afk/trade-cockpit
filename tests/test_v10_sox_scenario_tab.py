"""The SOX scenario tab (OWNER 2026-11-08 「今のキオクシア専用タブからこっちに変更して」).
The numbers stay on the OWNER's PC (RuntimeDir/sox_scenario_v1.json); the repo holds only the code that shows them."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SoxScenarioTab(unittest.TestCase):
    def test_gateway_route_and_flags(self):
        gw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/sox_scenario.json') {", gw)
        fn = gw[gw.index("function Get-SoxScenarioView"):]
        fn = fn[:fn.index("\n}\n") if "\n}\n" in fn else fn.index("\r\n}\r\n")]
        self.assertIn("[string]$view.schema_version -cne '100b-v10-sox-scenario-v1'", fn)
        self.assertIn("$view.real_submit_allowed -ne $false", fn)
        self.assertIn("$view.trade_instruction -ne $false", fn)
        self.assertIn("ReparsePoint", fn)

    def test_the_tab_shows_sox_and_keeps_the_kioxia_content(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-tab="kioxia-calendar">SOX</button>', html)
        self.assertIn('fold.id="kioxia-fold"', html)
        self.assertIn("SOXシナリオを読めません", html)
        self.assertIn('!el.classList.contains("cc-tab-owner-summary")', html)   # that box must stay directly under the pane
        self.assertIn("今朝の更新がありません", html)
        self.assertIn('w.schema_version==="100b-v10-sox-scenario-v1"&&w.real_submit_allowed===false&&w.trade_instruction===false', html)
        self.assertIn("起きると決まったものではありません", html)

    def test_the_tab_cannot_speak_or_order(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        block = html[html.index("SOX scenario chart replaces"):]
        block = block[:block.index("</script>")]
        for word in ("speak", "POST", "/order", "Speech"):
            self.assertNotIn(word, block)
        self.assertEqual(block.count("fetch("), 1)   # it only reads its own file


if __name__ == "__main__":
    unittest.main()
