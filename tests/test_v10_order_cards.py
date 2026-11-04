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
        self.assertIn("const qty = window.orderCardQty(entry);", self.block)
        self.assertIn('row("数量", qty + "株")', self.block)
        self.assertIn('["数量", qty]', self.block)

    def test_copy_buttons(self):
        for label in ('["コード",', '["指値", lim]', '["利確", tp]', '["損切り", sl]'):
            self.assertIn(label, self.block)
        self.assertIn('box.addEventListener("click", window.orderCardCopy)', self.block)


if __name__ == "__main__":
    unittest.main()
