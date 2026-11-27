"""GPT analysts' standing instructions in the アナリスト tab (OWNER 2026-11-03 「GPTのPRE-NEXT v3.0・需給 v2.2の指示：A（アナリストタブに入れる）」).
The instruction texts stay on the OWNER's PC (RuntimeDir/analyst_instructions_v1.json); the repo holds only the code that shows them."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AnalystInstructions(unittest.TestCase):
    def test_gateway_route_and_flags(self):
        gw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/analyst_instructions.json') {", gw)
        fn = gw[gw.index("function Get-AnalystInstructionsView"):]
        fn = fn[:fn.index("\n}\n") if "\n}\n" in fn else fn.index("\r\n}\r\n")]
        self.assertIn("[string]$view.schema_version -cne '100b-v10-analyst-instructions-v1'", fn)
        self.assertIn("$view.real_submit_allowed -ne $false", fn)
        self.assertIn("$view.trade_instruction -ne $false", fn)
        self.assertIn("Join-Path $RuntimeDir 'analyst_instructions_v1.json'", fn)

    def test_tab_folds_the_text_under_the_gpt_cards(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('get("/analyst_instructions.json")', html)
        self.assertIn('ins.schema_version==="100b-v10-analyst-instructions-v1"&&ins.real_submit_allowed===false', html)
        self.assertIn("if(c.id!==\"pre\"&&c.id!==\"sup\")return\"\";", html)            # GPT cards only
        self.assertIn("'+esc(x.text)+'</textarea>", html)                                # the text is escaped
        self.assertIn("基本の指示（読めません）", html)                                     # missing file shows a plain note
        self.assertIn("+baseFold(c)+", html)

    def test_instruction_texts_are_not_in_the_repo(self):
        # the texts carry PC folder names; only the PC copy holds them
        for name in ("index.html", "downloads/AI_COCKPIT_GATEWAY_V10.ps1"):
            text = (ROOT / name).read_text(encoding="utf-8-sig")
            self.assertNotIn("PRENEXT_NOTE_V3", text)
            self.assertNotIn("SUPPLY_NOTE_V22", text)


if __name__ == "__main__":
    unittest.main()
