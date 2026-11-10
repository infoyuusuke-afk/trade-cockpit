"""OWNER 2026-11-10 「トレード中の使い方が、やっぱりなんかよくわからない、同じようなものを整理まとめて、使い方を改善」
→ 「整理の案A承認。注文タブは無くす。見る銘柄は切り替え式」. Only the places of existing blocks change; their ids and code stay."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _block():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    start = html.index("/* OWNER 2026-11-10 「トレード中の使い方が、やっぱりなんかよくわからない")
    return html, html[start:html.index("</script>", start)]


class TradeLayout(unittest.TestCase):
    def test_order_tab_is_gone_but_its_pane_still_works(self):
        html, block = _block()
        self.assertIn('.cockpit-tab[data-tab="order"]{display:none!important}', block)
        # the pane is still built (its button must exist, or orderPaneMount builds another), so the cards keep being filled
        self.assertIn('if (!nav || !main || document.querySelector(\'.cockpit-tab[data-tab="order"]\')) return;', html)
        # a stored or open 注文 goes back to トレード中
        self.assertIn('if(op&&op.classList.contains("active")){const b=document.querySelector(\'.cockpit-tab[data-tab="scalp"]\');if(b)b.click();', block)
        self.assertIn('localStorage.setItem("cockpitTabV5","scalp")', block)

    def test_order_from_top_to_bottom(self):
        _, block = _block()
        # 1 the lamps beside the band  2 負け枠 first in the second band
        self.assertIn('mode.insertAdjacentElement("afterend",lamps)', block)
        self.assertIn("wrap.prepend(guard)", block)
        # 3 今やること  4 見る銘柄  5 サインの履歴  6 仮想の成績, in that order at the top of トレード中
        self.assertIn("[now,watch,hist,fold].forEach", block)
        for title in ("<h2>今やること", "<h2>見る銘柄", "<h2>サインの履歴", "<summary>仮想の成績（押すと開く）</summary>"):
            self.assertIn(title, block)

    def test_now_holds_the_cards_and_the_180s_signals(self):
        _, block = _block()
        self.assertIn('document.getElementById("order-pane-cards")', block)
        self.assertIn('document.getElementById("order-pane-rows")', block)
        self.assertIn('now.classList.toggle("tl-empty",emptyCards&&emptyRows)', block)
        self.assertIn("今はカードもサインもありません", block)
        # the old pane's own buttons still work here: 閉じる and copy
        self.assertIn('ev.target.closest("#tl-now")', block)
        self.assertIn("window.orderCardHeld&&window.orderCardHeld.delete(c.dataset.close)", block)
        self.assertIn("window.orderCardCopy(ev)", block)
        # the small duplicate cards and lines are hidden, not removed (the loader needs their slot)
        self.assertIn("#trade-watch{display:none!important}", block)
        self.assertIn("#attention-order-card{display:none!important}", block)

    def test_watch_is_a_switch(self):
        _, block = _block()
        self.assertIn('const VIEWS=[["sp8-panel","急変"],["opportunity-radar","実況"],["ai-top5","AI注目"]];', block)
        self.assertIn('el.classList.toggle("tl-show",id===view)', block)
        self.assertIn("#tl-watch .tl-slot>section:not(.tl-show){display:none!important}", block)
        self.assertIn('try{localStorage.setItem(KEY,view);}catch(_){}', block)

    def test_history_shows_three_then_all(self):
        _, block = _block()
        self.assertIn("#tl-history:not(.tl-all) #attention-rows>*:nth-child(n+4){display:none}", block)
        self.assertIn('"全部見る（"+n+"件）"', block)

    def test_virtual_is_folded(self):
        _, block = _block()
        self.assertIn('["virt-day-line","virt-held-line","cap-area","trade-fx-link"]', block)
        self.assertIn('"details"', block)

    def test_display_only(self):
        _, block = _block()
        for banned in ("fetch(", "RssOrder", "cockpitSpeak", "real_submit_allowed=true", "real_positions"):
            self.assertNotIn(banned, block)


if __name__ == "__main__":
    unittest.main()
