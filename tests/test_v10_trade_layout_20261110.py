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
        # a stored or open 注文 (or REALTIME 5) goes back to トレード中
        self.assertIn("const op=document.querySelector('.tab-pane[data-pane=\"order\"].active,.tab-pane[data-pane=\"ms2-live\"].active');", block)
        self.assertIn('if(op){const b=document.querySelector(\'.cockpit-tab[data-tab="scalp"]\');if(b)b.click();', block)
        self.assertIn('localStorage.setItem("cockpitTabV5","scalp")', block)

    def test_order_from_top_to_bottom(self):
        _, block = _block()
        # 1 the lamps beside the band  2 負け枠 first in the second band
        self.assertIn('txt.insertAdjacentElement("afterend",lamps)', block)   # since the one-look version: inside the band
        self.assertIn("wrap.prepend(guard)", block)
        # 3 今やること  4 見る銘柄  5 サインの履歴  6 仮想の成績, in that order at the top of トレード中
        self.assertIn("[now,watch,hist,fold].forEach", block)
        for title in ("<h2>今やること", "<h2>見る銘柄", "<h2>サインの履歴", "<summary>仮想の成績 <small class=\"tl-fold-hint\">押すと閉じる</small></summary>"):
            self.assertIn(title, block)

    def test_now_holds_the_cards_and_the_180s_signals(self):
        _, block = _block()
        self.assertIn('document.getElementById("order-pane-cards")', block)
        self.assertIn('document.getElementById("order-pane-rows")', block)
        self.assertIn('emptyRows=!rows||!!rows.querySelector(":scope > .ob-none")||!rows.children.length;', block)
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
        self.assertIn('const VIEWS=[["sp8-panel","急変"],["opportunity-radar","実況"],["ai-top5","AI注目"],["ms2-live-top5","今動いている5"],["premarket-gap-ranking","寄り前"],["watchlist-100","その他100銘柄"],["mel-live","メル300万"]];', block)   # OWNER 2026-11-11: メル300万 too
        # 寄り前 only 8:00-9:00 on weekdays (Tokyo); outside it the button is hidden and a stored 寄り前 shows 急変
        self.assertIn("return w>=1&&w<=5&&m>=480&&m<540;", block)
        # OWNER 2026-11-10 「見る銘柄は、8:00〜9:00は寄り前、9:00からは今動いている5を自動で開く。押して変えたら、その日はそのまま」
        self.assertIn('const autoView=()=>preOpen()?PRE:"ms2-live-top5";', block)
        self.assertIn('view=chosen&&chosen.day===today()?chosen.view:autoView(),shown=view===PRE&&!pre?"ms2-live-top5":view;', block)
        self.assertIn("chosen={view:v.dataset.tlView,day:today()};try{localStorage.setItem(KEY,JSON.stringify(chosen));}catch(_){}", block)
        self.assertIn("if(b.dataset.tlView===PRE)b.hidden=!pre;", block)
        self.assertIn('el.classList.toggle("tl-show",id===shown)', block)
        self.assertIn("#tl-watch .tl-slot>section:not(.tl-show){display:none!important}", block)
        # OWNER 2026-11-10 「急変のところ、文字がおさまってない」: the inner card's frame goes (.card sets its border with !important)
        self.assertIn("#tl-watch .tl-slot>section{width:100%;max-width:none;margin:0;box-sizing:border-box;border:0!important;border-radius:0!important;padding:0;", block)
        # audit 547f117: the boxes inside 今やること and 仮想の成績 keep no frame of their own
        self.assertIn("#tl-now>section.card{border:0!important;padding:0!important;margin:0!important;background:none!important;border-radius:0!important}", block)
        self.assertIn("#tl-virtual .vd-line,#tl-virtual .vd-held{min-height:0!important;border:0!important;", block)   # audit ac11723: no 58px floor inside the fold

    def test_history_shows_three_then_all(self):
        _, block = _block()
        self.assertIn("#tl-history:not(.tl-all) #attention-rows .attention-row:nth-child(n+4 of .attention-row){display:none}", block)
        # an empty history is one line
        self.assertIn('const n=document.querySelectorAll("#attention-rows .attention-row").length', block)
        self.assertIn('hist.classList.toggle("tl-empty",n===0);', block)
        self.assertIn("今日はまだサインがありません", block)

    def test_one_look_and_one_state_line(self):
        # OWNER 2026-11-10 「見た目を1つの決まりにそろえる。上は東証・ブレイン・Grokを1行の状態にまとめ、説明は止まった時だけ。
        # 箱は全部同じ角・余白・線・見出しの大きさ、見出しの下の線は消す。空の箱は1行」
        _, block = _block()
        self.assertIn("main .card{border-radius:14px!important;border:1px solid #303033!important;", block)
        # OWNER 2026-11-10 「負け枠・東証の帯・仮想の行の赤と緑は元の色に戻す」: only the corner is shared, never the colour
        self.assertIn("#unified-mode,.vd-line{border-radius:14px!important}", block)
        self.assertNotIn("#unified-mode,.vd-line{border-radius:14px!important;border:", block)
        self.assertIn("main .card{padding:16px 18px!important;margin:0 0 12px}", block)
        # OWNER 2026-11-10 later 「枠のサイズがバラバラだとかっこ悪い」: the band and the 負け枠 line use the same inner space as the boxes
        self.assertIn(".vd-line{padding:16px 18px!important;margin:0 0 12px!important;min-height:58px;box-sizing:border-box}", block)
        self.assertIn("gap:6px 18px;padding:16px 18px!important;margin:0 0 12px!important;min-height:58px!important;box-sizing:border-box}", block)
        self.assertIn("main .card h2{font-size:16px!important;line-height:1.35!important;border-bottom:0!important;padding-bottom:0!important;", block)
        # the lamps inside the band, their explanation only when red; the band's own explanation only when stopped in session
        self.assertIn('if(txt&&txt.nextElementSibling!==lamps)txt.insertAdjacentElement("afterend",lamps);', block)
        self.assertIn("#unified-mode .tl-status-lamps .brain-lamp:not(.red) small{display:none!important}", block)
        self.assertIn("#unified-mode:not(.lamp-down)>div:not(.unified-mode-controls):not(.tl-status-lamps)>:not(#unified-mode-title){display:none!important}", block)
        # inside the switch, the inner headings and the 急変 rule text go
        self.assertIn("#tl-watch .tl-slot>section>h2,#opportunity-radar .cc-opportunity-radar-head h2,#opportunity-radar .cc-opportunity-radar-head p,.sp8-rule{display:none!important}", block)
        self.assertIn('"全部見る（"+n+"件）"', block)

    def test_virtual_is_folded(self):
        _, block = _block()
        self.assertIn('["virt-day-line","virt-held-line","cap-area","trade-fx-link"]', block)   # OWNER 2026-11-11: the メル account live moved to 見る銘柄
        self.assertIn('["mel-live","メル300万"]', block)
        self.assertIn('"details"', block)

    def test_realtime_5_is_folded_in(self):
        # OWNER 2026-11-10 「REALTIME 5はさっき決めたとおり案2でタブを無くす。期待値ランキングの箱は消して、期待値の数字は今やることのサインの横に出す。
        # 手法別の成績の文はBRAINへ。…説明文は消す」
        html, block = _block()
        self.assertIn('.cockpit-tab[data-tab="ms2-live"]{display:none!important}', block)
        self.assertIn("#signal-ev-ranking{display:none!important}", block)
        self.assertIn('now.classList.toggle("tl-empty",emptyCards&&emptyRows);', block)
        # the EV beside each 180 s signal, from the same forward record as the order card; thin records say so
        self.assertIn('"</span>" + window.opRowEv(r.rule) + "</button>"', html)
        self.assertIn("window.opRowEv = rule => {", html)
        self.assertIn("if (!(n > 0) || !Number.isFinite(ev)) return \"<span class='op-ev'>期待値 —</span>\";", html)
        self.assertIn('根拠不足（" + n + "回）', html)
        # 手法別の成績 moves to BRAIN in its own box
        self.assertIn("const brain=document.querySelector('.tab-pane[data-pane=\"brain\"]'),sum=document.getElementById(\"signal-ev-summary\");", block)
        self.assertIn('if(sum.parentElement!==mb)mb.appendChild(sum);', block)
        # OWNER 2026-11-10 「ブレインの選択とGrokのX話題はBRAINのタブに移す」
        self.assertIn('const bp=document.getElementById("brain-pick-rows"),gx=document.getElementById("grok-rows");', block)
        self.assertIn("box(\"tl-brain-pick\",'<h2>ブレインの選択・GrokのX話題", block)
        self.assertIn("[bp,gx].forEach(el=>{if(el&&el.parentElement!==pb)pb.appendChild(el);});", block)
        # the explanations are hidden; the rows and the cards stay
        self.assertIn("#watchlist-100>p.sub,#premarket-gap-ranking>p.sub,#ms2-live-top5>p,#ms2-common-status{display:none!important}", block)
        for keep in ('id="watchlist-100-rows"', 'id="premarket-gap-rows"', 'id="ms2-live-cards"'):
            self.assertIn(keep, html)

    def test_cap_area_is_not_pulled_back(self):
        # audit 5d4b553: capArea() put the area back at the end of the hidden 注文 pane every 3 s
        html, _ = _block()
        self.assertIn('else if(!area.closest("#tl-virtual")&&(area.parentElement!==pane||area!==pane.lastElementChild))pane.appendChild(area);', html)

    def test_display_only(self):
        _, block = _block()
        for banned in ("fetch(", "RssOrder", "cockpitSpeak", "real_submit_allowed=true", "real_positions"):
            self.assertNotIn(banned, block)


if __name__ == "__main__":
    unittest.main()
