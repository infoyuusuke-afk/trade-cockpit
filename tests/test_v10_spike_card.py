"""急変カード (OWNER 2026-11-03 「なぜ株価が急激にうごいたかなどはリアルタイムに知りえる仕組みは組み込みたい」「急変カードを作って」)."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SpikeCard(unittest.TestCase):
    def setUp(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.block = html.split("「急変カードを作って」: during the session", 1)[1].split("})();", 1)[0]

    def test_trigger_rule(self):
        self.assertIn("MOVE=2.0,MOVE_V=1.0,VOLX=5,COOL=15*60000", self.block)
        self.assertIn("Math.abs(m.chg)>=MOVE||(m.volx!=null&&m.volx>=VOLX&&Math.abs(m.chg)>=MOVE_V)", self.block)
        self.assertIn("(m>=540&&m<=690)||(m>=750&&m<=930)", self.block)                # the session only
        self.assertIn("window.cockpitMs2ScreenReady?.(d)!==true", self.block)            # fresh data only
        self.assertIn("window.cockpitMs2RowReady?.(x)===true", self.block)
        self.assertIn("Date.now()-(st.last[code]||0)<COOL", self.block)                 # once per stock per 15 minutes

    def test_reasons_are_facts_not_guesses(self):
        self.assertIn('get("/tdnet_today.json")', self.block)
        self.assertIn('v.schema_version==="100b-v10-tdnet-today-v1"&&v.real_submit_allowed===false', self.block)
        self.assertIn("今日の開示は見つかっていません", self.block)
        self.assertIn("TDnetの一覧を読めません（理由は未確認）", self.block)
        self.assertIn("今日が決算の予定日です（JPXの予定・時刻は未確認）", self.block)
        self.assertIn('rel="noopener"', self.block)
        for banned in ("RssOrder", "renderAttention", "real_submit_allowed:true"):
            self.assertNotIn(banned, self.block)

    def test_collector_and_gateway(self):
        col = (ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("schema_version = '100b-v10-tdnet-today-v1'", col)
        self.assertIn("Write-AtomicUtf8 (Join-Path $PSScriptRoot 'tdnet_today_v1.json')", col)
        i = col.index("schema_version = '100b-v10-tdnet-today-v1'")
        self.assertIn("} catch {}", col[i:i + 900])                                       # a failed write never stops it
        gw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/tdnet_today.json') {", gw)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-tdnet-today-v1'", gw)


if __name__ == "__main__":
    unittest.main()
