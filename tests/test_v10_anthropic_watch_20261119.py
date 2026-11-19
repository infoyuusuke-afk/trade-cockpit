"""OWNER 2026-11-19 「アンソロピック関連10銘柄を…前夜のANTの値動きも1行出して…画面のテーマ欄は手法タブの版に入れて」: a card at the top of the
テーマ tab from /anthropic_watch.json (RuntimeDir anthropic_watch_v1.json, written by the PC). Display only."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8")


def card():
    a = HTML.index("OWNER 2026-11-19 「アンソロピック関連10銘柄を")
    return HTML[a:HTML.index("</script>", a)]


class Gateway(unittest.TestCase):
    def test_route_and_checks(self):
        self.assertIn("if ($path -eq '/anthropic_watch.json') {", GW)
        a = GW.index("function Get-AnthropicWatchView(")
        fn = GW[a:GW.index("function Get-ClosingLockView(", a)]
        for w in ("'anthropic_watch_v1.json'", "-gt 65536", "ReparsePoint", "'100b-v10-anthropic-watch-v1'",
                  "real_submit_allowed -ne $false", "trade_instruction -ne $false", "503 Service Unavailable"):
            self.assertIn(w, fn)
        fn.encode("ascii")


class Card(unittest.TestCase):
    def test_in_theme_tab_top(self):
        w = card()
        self.assertIn('.tab-pane[data-pane="pre-next"]', w)
        self.assertIn('sec.id="anthropic-watch"', w)
        self.assertIn("intro.after(sec)", w)
        self.assertIn('fetch("/anthropic_watch.json?t="', w)

    def test_only_safe_documents(self):
        self.assertIn('v.schema_version!=="100b-v10-anthropic-watch-v1"||v.real_submit_allowed!==false||v.trade_instruction!==false', card())

    def test_ant_line_and_escape(self):
        w = card()
        self.assertIn("ANT（ナスダック）", w)
        for f in ("esc(s.name)", "esc(s.code)", "esc(s.role)", "esc(v.note", "esc(a.base"):
            self.assertIn(f, w)

    def test_display_only(self):
        w = card()
        for bad in ("speak", "speechSynthesis", "order_card", "submitOrder", "localStorage.setItem"):
            self.assertNotIn(bad, w)


if __name__ == "__main__":
    unittest.main()
