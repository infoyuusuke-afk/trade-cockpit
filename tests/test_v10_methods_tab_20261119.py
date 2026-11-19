"""OWNER 2026-11-19 「手法がおおくなったから手法タブをつくって、全ての手法を書き出して、今日の使う手法を上部に表示してわかりやすく見やすくつくって」:
a 手法 tab from /methods_catalog.json (RuntimeDir methods_catalog_v1.json, written by the PC's methods_catalog.py). Display only."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8")


def tab_block():
    a = HTML.index("OWNER 2026-11-19 「手法がおおくなったから手法タブをつくって")
    return HTML[a:HTML.index("</script>", a)]


class Gateway(unittest.TestCase):
    def test_route_and_checks(self):
        self.assertIn("if ($path -eq '/methods_catalog.json') {", GW)
        a = GW.index("function Get-MethodsCatalogView(")
        fn = GW[a:GW.index("\n}\n", a) if "\n}\n" in GW[a:] else GW.index("\r\n}\r\n", a)]
        for w in ("'methods_catalog_v1.json'", "-gt 131072", "ReparsePoint", "'100b-v10-methods-catalog-v1'",
                  "real_submit_allowed -ne $false", "trade_instruction -ne $false", "503 Service Unavailable"):
            self.assertIn(w, fn)

    def test_gateway_addition_is_ascii(self):
        a = GW.index("# OWNER 2026-11-19 \"make a methods tab")
        b = GW.index("# OWNER 2026-11-17 (15:24 lock)")
        GW[a:b].encode("ascii")
        r = GW.index("if ($path -eq '/methods_catalog.json') {")
        GW[r:r + 400].encode("ascii")


class Tab(unittest.TestCase):
    def test_tab_and_row(self):
        self.assertIn('"analysts","methods","kioxia-calendar"', HTML)
        w = tab_block()
        self.assertIn('b.dataset.tab="methods"', w)
        self.assertIn('pane.dataset.pane="methods"', w)
        self.assertIn('fetch("/methods_catalog.json?t="', w)

    def test_only_safe_documents_are_shown(self):
        w = tab_block()
        self.assertIn('j.schema_version==="100b-v10-methods-catalog-v1"&&j.real_submit_allowed===false&&j.trade_instruction===false', w)

    def test_today_on_top_then_every_method(self):
        w = tab_block()
        i_top, i_ck, i_rs = w.index("今日使う手法（メル・"), w.index("コクピットの手法（メルが選ぶ元）"), w.index("研究の前向きの記録（E〜K")
        self.assertLess(i_top, i_ck)
        self.assertLess(i_ck, i_rs)
        self.assertIn("今日使う</span>", w)

    def test_text_is_escaped(self):
        w = tab_block()
        for field in ("m.rule", "m.name", "m.where", "m.verdict", "tp.reason", "data.note"):
            self.assertRegex(w, r"esc\(%s(\)|\|\|)" % re.escape(field))
        self.assertNotRegex(w, r"'\+m\.(rule|name|where|verdict)\+'")

    def test_full_width(self):
        """OWNER 2026-11-20 「タブのサイズがなんで画面の半分」: the tab's pane is a two-column grid; the body spans both columns"""
        self.assertIn("#mt-body{padding:0 4px 16px;grid-column:1/-1}", tab_block())

    def test_two_columns_now_and_analyst(self):
        """OWNER 2026-11-20 「画面左が今までのメルの手法、画面右がアナリストをいれた手法」"""
        w = tab_block()
        self.assertIn(".mt-vs{display:grid;grid-template-columns:1fr 1fr", w)
        self.assertLess(w.index("'<div class=\"mt-vs\">'+left+right"), w.index("比べる相手："))
        self.assertIn("今のメル<small>今までの決まり</small>", w)
        self.assertIn("アナリスト入りメル<small>", w)
        self.assertIn('dir==="強気"?["R1","R4"].includes(c):dir==="弱気"?["R2","R5"].includes(c)', w)
        self.assertIn("esc(r.name)", w)
        self.assertIn("esc(r.stance)", w)

    def test_display_only(self):
        w = tab_block()
        for bad in ("speak", "speechSynthesis", "order_card", "submitOrder", "method:\"POST\"", "localStorage.setItem(\"cockpitMethods"):
            self.assertNotIn(bad, w)
        self.assertNotIn("real_submit_allowed===true", w)


if __name__ == "__main__":
    unittest.main()
