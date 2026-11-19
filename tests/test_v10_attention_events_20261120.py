"""OWNER 2026-11-20 「アンソロピック上場と日本、米国、中国、ロシアなどの会談イベントがでてなかった、注意タブ非常に弱い、改善しろ」:
the 注意 tab's 『大きく動きそうな日』 also shows /attention_events.json (RuntimeDir attention_events_v1.json, the PC's
attention_events.py: summits, holidays abroad, central banks with an official date, large new listings from JPX). Display only."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8")


def block():
    a = HTML.index("OWNER 2026-11-20 「アンソロピック上場と日本、米国、中国、ロシアなどの会談イベントがでてなかった")
    return HTML[a:HTML.index("</script>", a)]


class Gateway(unittest.TestCase):
    def test_route_and_checks(self):
        self.assertIn("if ($path -eq '/attention_events.json') {", GW)
        a = GW.index("function Get-AttentionEventsView(")
        fn = GW[a:GW.index("# OWNER 2026-11-17 (15:24 lock)", a)]
        for w in ("'attention_events_v1.json'", "-gt 65536", "ReparsePoint", "'100b-v10-attention-events-v1'",
                  "real_submit_allowed -ne $false", "trade_instruction -ne $false", "503 Service Unavailable"):
            self.assertIn(w, fn)

    def test_gateway_addition_is_ascii(self):
        a = GW.index("# OWNER 2026-11-20 \"the attention tab is very weak")
        GW[a:GW.index("# OWNER 2026-11-17 (15:24 lock)", a)].encode("ascii")
        r = GW.index("if ($path -eq '/attention_events.json') {")
        GW[r:r + 300].encode("ascii")


class Card(unittest.TestCase):
    def test_reads_and_checks_the_file(self):
        w = block()
        self.assertIn('get("/attention_events.json")', w)
        self.assertIn('v.schema_version==="100b-v10-attention-events-v1"&&v.real_submit_allowed===false&&v.trade_instruction===false', w)
        self.assertIn("(aeOk(ae)?ae.events:[]).forEach(", w)
        self.assertIn("報道で出ている予定（公式の発表ではない）", w)

    def test_text_is_escaped(self):
        w = block()
        for f in ("esc(i.cat)", "esc(i.memo)", "esc(i.src)", "esc(x.category)", "esc(x.title)", "esc(x.note)", "esc(ae.ipo_state",
                  "esc(day(x.date))", "esc(x.time)", "esc(s)", "esc(s&&s.name)", "esc(s&&s.code)", "esc(u)"):
            self.assertIn(f, w)

    def test_reported_section(self):
        """OWNER 2026-11-20 「…別の欄『報道で出ている予定（公式の発表ではない）』として日付順に出し、日付が決まっていないものは『日付未定』。表示だけ」"""
        w = block()
        self.assertIn('return "日付未定";', w)
        self.assertIn("box.insertAdjacentHTML(\"beforeend\",reportedHtml(ae));", w)
        # links: only http(s), opened apart from the cockpit
        self.assertIn("const safeUrl=u=>/^https?:\/\/[^\s\"'<>]+$/.test(String(u||\"\"))?String(u):\"\";", w)
        self.assertIn('target="_blank" rel="noopener noreferrer"', w)

    def test_display_only(self):
        w = block()
        for bad in ("speak", "speechSynthesis", "order_card", "submitOrder", "method:\"POST\""):
            self.assertNotIn(bad, w)


if __name__ == "__main__":
    unittest.main()
