"""OWNER 2026-11-17 「保有中が一目でわかる形」 and then 「保有と持ち越しを一目で見る版を作って。SWING 5・長期・OVERNIGHT 5・メルの各タブの上に
1銘柄1行の一覧表（銘柄・向き・株数・今値・含み%・損益円・STOPまで%・TARGETまで%・日数）。株数は大きく、OVERNIGHT 5にも出す。結果が出たら大きな札：
勝ち=緑+円、負け=赤−円、待ち=灰、0株=見送りで薄く。メルの表は通常/半分/AIを1行にまとめる。含み損の大きい順、STOPまで1%以内は赤帯、合計行。
今のカードは表の下にたたむ。1130pxではみ出さない。表示だけ、注文しない」."""
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


def code_only(block):
    return "\n".join(l for l in block.splitlines() if not l.lstrip().startswith("//"))


class SharedTable(unittest.TestCase):
    def setUp(self):
        i = HTML.index("window.cockpitHoldList(rows, caption)")
        self.js = HTML[i:HTML.index("</script>", i)]

    def test_columns_and_big_shares(self):
        self.assertIn("<th>結果</th><th>銘柄</th><th>向き</th><th>株数</th><th>今値</th><th>含み%</th><th>損益円</th><th>STOPまで</th><th>TARGETまで</th><th>日数</th>", self.js)
        self.assertIn(".hl-sh{font-size:18px;font-weight:800;", HTML)

    def test_badges(self):
        self.assertIn('<span class="hl-badge win">勝ち \'+yen(r.resultYen)+\'</span>', self.js)
        self.assertIn('<span class="hl-badge lose">負け \'+yen(r.resultYen)+\'</span>', self.js)
        self.assertIn('<span class="hl-badge skip">見送り</span>', self.js)
        self.assertIn('<span class="hl-badge wait">待ち</span>', self.js)
        self.assertIn(".hl-tbl tr.hl-skip td{opacity:.45}", HTML)

    def test_order_band_total(self):
        # the biggest loss first, 見送り last; the stop within 1% -> red band; a total line
        self.assertIn('(a.result==="skip")-(b.result==="skip")||(fin(a.yen)?Number(a.yen):1e15)-(fin(b.yen)?Number(b.yen):1e15)', self.js)
        self.assertIn('const near=r.result!=="skip"&&fin(r.stopPct)&&Math.abs(Number(r.stopPct))<=1;', self.js)
        self.assertIn('<tr class="hl-total"><td>合計</td>', self.js)
        self.assertIn("table-layout:fixed", HTML)                                       # 1130 px: the columns share the box

    def test_display_only(self):
        code = code_only(self.js)
        for word in ("fetch(", "cockpitSpeak", "/control", "RssOrder"):
            self.assertNotIn(word, code)


class EachTab(unittest.TestCase):
    def test_swing_and_long(self):
        self.assertIn('return window.cockpitHoldList?window.cockpitHoldList(rows,label+"（仮想・100株ずつ・費用なし）　含み損の大きい順"):"";', HTML)
        self.assertIn("holdTable(open,all,label)+(open.length?'<details class=\"ht8-cards\"", HTML)
        self.assertIn('if(d&&d.classList&&d.classList.contains("ht8-cards"))cardsOpen[d.dataset.k]=d.open;', HTML)

    def test_overnight(self):
        i = HTML.index("「保有と持ち越しを一目で見る版」 (OVERNIGHT 5)")
        b = HTML[i:HTML.index("</script>", i)]
        self.assertIn('["ms2-hold-cards","on-compare"].forEach(id=>{const el=document.getElementById(id);if(el&&fold&&el.parentElement!==fold)fold.append(el);});', b)
        self.assertIn("shares:100", b)
        self.assertIn('sub:[one("通常"),one("半分"),one("AI")].join("　")', b)   # 通常/半分/AI on one line (the night's own events follow)
        self.assertIn('((r.events||[]).length?"　翌朝の注意："+r.events.join("・"):"")', b)
        # audit c5be6b0: the card marks (決算またぎ・決算予定 未確認・翌朝の注意・NVIDIA決算の夜) stay visible on the rows
        for mark in ("📅 決算またぎ（", "📅 決算予定 未確認", "⚠ 翌朝の注意：", "🔶 半導体・NVIDIA決算の夜"):
            self.assertIn(mark, b)
        self.assertIn("sub:marks(x).join(\"　\")", b)
        self.assertIn('result:sh<=0?"skip":r.closed?(y>0?"win":y<0?"lose":"wait"):"wait"', b)
        self.assertIn("bp.real_submit_allowed===false", b)
        code = code_only(b)
        for word in ("cockpitSpeak", "/control", "RssOrder"):
            self.assertNotIn(word, code)

    def test_mel(self):
        self.assertIn("ml.innerHTML=melTable()+'<details class=\"hl-fold\"'+(window.__hlMelOpen?' open':'')+'><summary>前の表（たたむ）</summary>'+melLiveHtml()+'</details>';", HTML)
        self.assertIn('result:sh<=0?"skip":done?(y>0?"win":y<0?"lose":"wait"):"wait"', HTML)


if __name__ == "__main__":
    unittest.main()
