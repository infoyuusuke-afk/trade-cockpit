"""OWNER 2026-11-12 「コクピットに今日の相場の型を一言で出す版を作って（8:11の記録から、意味を一文で、検証中と書く、売買サインにしない、型が出た日は8:40の声で1回だけ）」."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")


class MarketTypesLine(unittest.TestCase):
    def test_gateway_serves_it_only_with_safe_flags(self):
        self.assertIn("function Get-MarketTypesView([string]$RuntimeDir) {", GW)
        self.assertIn("$file = Join-Path $RuntimeDir 'market_types_today_v1.json'", GW)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-market-types-v1' -or $view.real_submit_allowed -ne $false", GW)
        self.assertIn("if ($path -eq '/market_types.json') {", GW)

    def test_one_line_today_only_and_not_a_signal(self):
        self.assertIn("<div id='trade-sched-lamp'></div><div id='trade-type-line'></div></div>", HTML)
        i = HTML.index("const renderTypes=()=>{")
        block = HTML[i:HTML.index("setInterval(renderTypes,60000);", i)]
        self.assertIn('if(!j||String(j.day||"")!==today){el.innerHTML="";', block)   # only today's 8:11 record
        self.assertIn('"今日の型："+names+"（検証中）　"+meaning+"・売買サインではない"', block)
        self.assertIn('"今日の型：なし（検証中）"', block)
        # audit cb25546: stays inside the band; OWNER 2026-11-12 「もじがきれてる」: wraps instead of being cut with …
        self.assertIn("#trade-type-line .type-line{display:inline-block;font-size:13px;color:#cdb8f0;white-space:normal;overflow-wrap:anywhere;max-width:100%;", HTML)
        i = HTML.index("#trade-type-line .type-line{")
        self.assertNotIn("text-overflow:ellipsis", HTML[i:i + 300])
        self.assertIn("esc(text)", block)
        # 「声の1文を一緒に版にして」: once a day, 8:40-9:00, only with a type, after the stop-loss band
        self.assertIn("if(ts.length&&np.min>=520&&np.min<540&&typeof window.cockpitSpeak===\"function\"){", block)
        self.assertIn('if(said!==today&&window.__typesSpoken!==today&&!stopOn){', block)
        self.assertIn('localStorage.setItem("cockpitTypesSpokenV1",today)', block)
        self.assertIn("検証中で、予測ではありません。", block)
        self.assertNotIn("#35e2ae", block)
        self.assertNotIn("#f23645", block)


if __name__ == "__main__":
    unittest.main()
