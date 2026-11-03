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

    def test_tdnet_not_read_and_voice_once_a_minute(self):
        # OWNER 2026-11-03 「TDnetの状態が『TDnet確認済み』でない時は『TDnetを読めていません』…時刻は最後に読めた時刻…
        # 急変が一度にいくつも出た時は、声は1分に1回にまとめて『急変 何銘柄』と一番大きい銘柄だけ言って」
        self.assertIn('tdOk=!!(td&&/^TDnet確認済み/.test(String(td.status||"")));', self.block)
        self.assertIn('"TDnetを読めていません（"+lastOkText()+"）。開示があるかは未確認です"', self.block)
        self.assertIn('"最後に読めた時刻 "', self.block)
        self.assertIn('ティーディーネットを読めていません。', self.block)
        self.assertIn("Date.now()-lastVoice<60000", self.block)
        self.assertIn('(n>1?"急変 "+n+"銘柄。一番大きいのは、":"急変。")', self.block)
        self.assertIn("sort((a,b)=>Math.abs(b.chg)-Math.abs(a.chg))[0]", self.block)
        col = (ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$tdnetLastOkAt=$now}", col)                                         # set only on a good read
        self.assertIn("last_ok_at = if ($null -ne $tdnetLastOkAt)", col)

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
