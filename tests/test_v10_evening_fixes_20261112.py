"""OWNER 2026-11-12 「とまってる」「ロング　ショート　分からない」「ロング・ショート分からない」「これってお合ってるの」."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
CTL = (ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")


class EveningFixes(unittest.TestCase):
    def test_controller_state_write_never_stops_the_controller(self):
        i = CTL.index("function Save-State($state) {")
        block = CTL[i:CTL.index("\n}", i)]
        self.assertIn("Move-Item -LiteralPath $tmp -Destination $StateFile -Force -ErrorAction Stop; return } catch { Start-Sleep -Milliseconds 100 }", block)
        self.assertIn("for ($i = 0; $i -lt 20; $i++) {", block)
        self.assertIn("[IO.File]::WriteAllText($StateFile, $json", block)
        self.assertIn("State file busy - this write skipped", block)

    def test_gpt_cards_show_long_short(self):
        self.assertIn('const vw=String(x.view||""),gdir=/強気/.test(vw)?"long":/弱気/.test(vw)?"short":"";', HTML)
        self.assertIn('"▲ LONG（買い）":gdir==="short"?"▼ SHORT（空売り）":"― 向き なし"', HTML)

    def test_grok_cards_show_long_short_or_wait(self):
        self.assertIn('"long\'>▲ LONG（買い）" : k === "short" ? "short\'>▼ SHORT（空売り）" : "none\'>― 様子見"', HTML)
        self.assertIn(".dir-chip.long{", HTML)

    def test_holds_keep_todays_last_price_after_the_close(self):
        self.assertIn('localStorage.setItem("cockpitLastPricesV1",JSON.stringify(window.cockpitLastPrices))', HTML)
        self.assertIn("if(k&&k.day===today&&k.rows)window.cockpitLastPrices=k;", HTML)
        self.assertIn('tag="今日の最後の値（MS2・"+(lq.asof||"時刻不明")+"）";', HTML)

    def test_grok_wait_words_before_the_bracket_win(self):
        self.assertIn('const w = String(v || "").split(/[（(]/)[0]; return /見送り|様子見|監視/.test(w) ? "wait"', HTML)

    def test_kept_prices_only_for_today(self):
        self.assertIn("last=lq&&lq.day===new Date(Date.now()+9*3600e3).toISOString().slice(0,10)?Number(lq.rows&&lq.rows[code]):NaN;", HTML)


if __name__ == "__main__":
    unittest.main()
