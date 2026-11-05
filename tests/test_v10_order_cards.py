"""Order cards for positive-EV picks (OWNER 2026-11-04 「期待値の高い銘柄は注文カードまですぐだせるように　おれの操作はほぼなくす事」)."""
from pathlib import Path
import unittest

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


class OrderCards(unittest.TestCase):
    def setUp(self):
        self.block = HTML[HTML.index("window.ORDER_CARD_CODES"):HTML.index("window.loadGrokBots = () =>")]

    def test_positive_ev_picks_and_285a(self):
        self.assertIn('Number(s.side) !== 0 && (window.ORDER_CARD_CODES.includes(String(s.ticker)) || Number(s.ev_pct) > 0)', self.block)
        self.assertIn("(b.picks || []).filter(window.orderCardWanted)", self.block)

    def test_card_stays_display_only(self):
        self.assertIn("b.real_submit_allowed === false", self.block)
        self.assertIn("検証中", self.block)
        self.assertIn("navigator.clipboard.writeText(b.dataset.copy)", self.block)
        for banned in ("RssOrder", "RssStockOrder", "sendKeys", "/order", "real_submit_allowed = true", "real_submit_allowed:true"):
            self.assertNotIn(banned, self.block)

    def test_quantity_follows_the_price(self):
        # OWNER 2026-11-04 「5000円未満200株、あとは100株単位」
        self.assertIn("window.orderCardQty = price => (Number(price) < 5000 ? 200 : 100);", self.block)
        self.assertIn("const qty = window.orderCardQty(lim);", self.block)                # after rounding
        self.assertIn('row("数量", qty + "株")', self.block)
        self.assertIn('["数量", qty]', self.block)

    def test_tick_tables(self):
        # OWNER 2026-11-04 「呼値を銘柄ごとに正しい刻みにして、分からない時は粗いほうで丸めて」
        self.assertIn("window.TSE_TICK_FINE = [[1000,0.1],[3000,0.5],[10000,1],[30000,5],[100000,10],[300000,50]", self.block)
        self.assertIn("window.TSE_TICK_COARSE = [[3000,1],[5000,5],[30000,10],[50000,50],[300000,100],[500000,500]", self.block)
        self.assertIn('window.ORDER_CARD_FINE_TICK.includes(String(ticker || "").replace(".T", "")) ? window.TSE_TICK_FINE : window.TSE_TICK_COARSE', self.block)
        self.assertIn('window.roundTick(entry, buy ? "down" : "up", s.ticker)', self.block)
        self.assertIn('window.roundTick(stop, buy ? "down" : "up", s.ticker)', self.block)
        codes = self.block.split("window.ORDER_CARD_FINE_TICK = ", 1)[1].split(";", 1)[0]
        self.assertIn('"285A"', codes)
        self.assertNotIn('"186A"', codes)                               # not on the list -> the coarse table

    def test_thin_record_is_marked(self):
        # OWNER 2026-11-04 「実績20回未満のカードには『実績不足』と出して」
        self.assertEqual(self.block.count("Number(s.forward_n ?? 0) < 20"), 2)
        self.assertIn("実績不足（", self.block)

    def test_card_is_held_after_the_pick_goes(self):
        # OWNER 2026-11-05 「注文カードでないぞ」
        self.assertIn('held.set(k, {s, at: nowMs})', self.block)
        self.assertIn('nowMs - v.at >= window.ORDER_CARD_TTL_MS', self.block)
        self.assertIn('window.orderCardHtml(v.s, v.at, nowMs)', self.block)
        self.assertIn('if (b && b.real_submit_allowed !== false) held.clear();', self.block)

    def test_row_click_opens_the_card(self):
        # OWNER 2026-11-05 「ここで銘柄クリックすると注文カードが出る仕組み」
        self.assertIn("""r.kind==="RULE"&&r.target&&r.stop?' att-click" data-att-i="'+i""", HTML)
        self.assertIn('window.attentionCardRows=list;', HTML)
        self.assertIn('ev.target.closest("#attention-rows .att-click")', self.block)
        self.assertIn('window.orderCardHtml(s, at, Date.now())', self.block)
        self.assertIn('data-close', self.block)

    def test_copy_buttons(self):
        for label in ('["コード",', '["指値", lim]', '["利確", tp]', '["損切り", sl]'):
            self.assertIn(label, self.block)
        self.assertIn('box.addEventListener("click", window.orderCardCopy)', self.block)


if __name__ == "__main__":
    unittest.main()
