"""OWNER 2026-11-16 「毎朝8:35に…その日の注目銘柄を10前後選んで、理由を付けて9:00前に固めて。ロング・ショート・様子見に分けて…
コクピットのAI注目にも、ロングは緑・ショートは赤で分けて出す。引け後に当たり外れを記録する。注文はしない」."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")


def _block():
    i = HTML.index("「毎朝8:35に、コクピットの全部のアナリスト・テクニカル・板の記録・PTS・決算・Grokを使って")
    return HTML[i:HTML.index("</script>", i)]


class AiFocusPicks(unittest.TestCase):
    def test_gateway_serves_it_only_with_safe_flags(self):
        self.assertIn("function Get-AiFocusView([string]$RuntimeDir) {", GW)
        self.assertIn("$file = Join-Path $RuntimeDir 'ai_focus_v1.json'", GW)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-ai-focus-v1' -or $view.real_submit_allowed -ne $false", GW)
        self.assertIn("if ($path -eq '/ai_focus.json') {", GW)
        i = GW.index("function Get-AiFocusView")
        self.assertTrue(all(ord(ch) < 128 for ch in GW[i:GW.index("\n}", i)]))

    def test_long_green_short_red_wait_grey_today_only(self):
        b = _block()
        self.assertIn('[["買い","ロング","af-long"],["売り","ショート","af-short"],["様子見","様子見","af-wait"]]', b)
        self.assertIn("#ai-focus-picks .af-long .af-chip{border-color:#164536;color:#35e2ae;background:#0d2b23}", HTML)
        self.assertIn("#ai-focus-picks .af-short .af-chip{border-color:#4a1f24;color:#ff8a8f;background:#2a1215}", HTML)
        # OWNER 2026-11-17: today only, and only when locked before 9:00
        self.assertIn("const picks=v.day===today&&beforeOpen&&Array.isArray(v.picks)?v.picks:[];", b)
        self.assertIn("に固定（後から変えません）・", b)
        self.assertIn("AI注目の記録を読めません（0件とは扱いません）。", b)
        self.assertIn("の結果（寄り→引け・費用0.1%引き）：", b)

    def test_text_only_no_voice_no_order(self):
        code = "\n".join(line for line in _block().splitlines() if not line.lstrip().startswith("//"))
        self.assertNotIn("innerHTML", code)
        for word in ("cockpitSpeak", "speechSynthesis", "order", "renderCockpitCard"):
            self.assertNotIn(word, code)
        self.assertIn("v.real_submit_allowed!==false||v.trade_instruction!==false", code)


class AiFocusNightAndClean(unittest.TestCase):
    def test_no_lock_yet_is_not_a_read_error(self):
        b = _block()
        self.assertIn('missing=!r.ok&&!!j&&j.reason==="AI_FOCUS_MISSING";', b)
        self.assertIn("まだ1回も固めていません（平日8:50ごろに固まります）。", b)

    def test_gateway_has_no_control_characters(self):
        raw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_bytes()
        self.assertFalse(any(c < 32 and c not in (9, 10, 13) for c in raw))   # audit 3a77cc6: a BEL in a comment
        self.assertIn(r"RuntimeDir\ai_focus_v1.json, written", GW)
        self.assertIn(r"RuntimeDir\brain_pick_v1.json", GW)
        self.assertIn(r"RuntimeDir\trial_methods_v1.json is written", GW)


if __name__ == "__main__":
    unittest.main()
