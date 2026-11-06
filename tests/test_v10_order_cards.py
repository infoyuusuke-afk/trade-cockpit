"""Order cards for positive-EV picks (OWNER 2026-11-04 「期待値の高い銘柄は注文カードまですぐだせるように　おれの操作はほぼなくす事」)."""
from pathlib import Path
import unittest

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


class OrderCards(unittest.TestCase):
    def setUp(self):
        self.block = HTML[HTML.index("window.ORDER_CARD_CODES"):HTML.index("window.loadGrokBots = () =>")]

    def test_positive_ev_picks_and_285a(self):
        self.assertIn('(window.ORDER_CARD_CODES.includes(String(s.ticker)) || Number(s.ev_pct) > 0)', self.block)
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
        self.assertIn(' att-click" data-att-t="', HTML)
        self.assertNotIn("data-att-i", HTML)                             # never by row number
        self.assertIn('window.attentionCardRows=list;', HTML)
        self.assertIn('ev.target.closest("#attention-rows .att-click")', self.block)
        self.assertIn('held.set(k, {s, at, pinned: true})', self.block)
        # OWNER 2026-11-05 「上の画面で一目でわかる仕組みにして」: the line sits above the list in 注目, on every tab
        self.assertIn('box.insertAdjacentElement("beforebegin", slot)', self.block)
        self.assertIn('window.orderCardQty(lim)', self.block[self.block.index("window.orderLineHtml"):])
        self.assertIn('実績不足', self.block[self.block.index("window.orderLineHtml"):])
        self.assertIn('if (nowMs - v.at >= window.ORDER_CARD_TTL_MS) held.delete(k);', self.block)
        self.assertIn('data-close', self.block)

    def test_big_view(self):
        # OWNER 2026-11-05 「注文カードはクリックするとこんなふうに大きく表示出来るようにして老眼だから、小さいとみえない」
        big = self.block[self.block.index("window.orderBigHtml = (k, v, closeAttr) =>"):]
        self.assertIn('window.orderBigOpen(l.dataset.ol)', self.block)
        self.assertIn('window.orderBigOpen(k);', self.block)
        for label in ('btn("コード"', 'btn("数量"', 'btn("指値"', 'btn("利確 "', 'btn("損切 "'):
            self.assertIn(label, big)
        self.assertIn("window.orderCardQty(lim)", big)
        self.assertIn('ev.key === "Escape"', self.block)
        self.assertIn(".ob-grid b{font-size:20px", HTML)   # OWNER 2026-11-06 「半分くらいのサイズで一回つくって」
        for banned in ("RssOrder", "RssStockOrder", "real_submit_allowed = true"):
            self.assertNotIn(banned, big)

    def test_order_tab(self):
        # OWNER 2026-11-05 「注文タブつくって、ほかはとりあえずよい」
        self.assertIn('b.dataset.tab = "order";', self.block)
        self.assertIn('b.textContent = "注文";', self.block)
        self.assertIn("""nav.querySelector('.cockpit-tab[data-tab="scalp"]')""", self.block)
        self.assertIn('window.orderBigHtml(k, v, "data-close=', self.block)
        self.assertIn('r.kind === "RULE" && r.target && r.stop && (r.signal === "買いサイン" || r.signal === "空売りサイン")', self.block)
        self.assertIn('window.attentionCardOpen(inTab, true)', self.block)
        pane = self.block[self.block.index("window.orderPaneRender = () =>"):self.block.index("window.orderPaneMount = () =>")]
        for banned in ("RssOrder", "RssStockOrder", "real_submit_allowed = true"):
            self.assertNotIn(banned, pane)

    def test_row_is_found_by_stock_and_time(self):
        # OWNER 2026-11-05 「押した行の銘柄と時刻でカードを探すようにして、隣の行のカードが出ないようにして」
        self.assertIn("x.ticker === row.dataset.attT && String(x.captured_at) === row.dataset.attAt", self.block)
        # 「買いか空売りか分からない合図にはカードを出さないで」
        self.assertIn('if (!r || (r.signal !== "買いサイン" && r.signal !== "空売りサイン") || window.ORDER_CARD_NO_RULES.includes(String(r.rule))) return;', self.block)

    def test_old_card_has_no_copy_buttons(self):
        # OWNER 2026-11-05 「古くなったカードはコピーボタンを消して」
        self.assertEqual(self.block.count("const btn = (label, val, shown) => left > 0 ?"), 2)
        self.assertIn("(left <= 0 ? \"\" : \"<div class='order-card-copy'>\"", self.block)

    def test_order_tab_hides_the_boxes(self):
        # OWNER 2026-11-05 「注文タブを開いている時は、貼り忘れとショートリバの箱を隠して、カードを上に詰めて」
        self.assertIn('document.body.classList.toggle("order-open"', self.block)
        self.assertIn("body.order-open #paste-reminder,body.order-open #short-rebound-alert", HTML)

    def test_r4_has_no_card(self):
        # OWNER 2026-11-05 「R4(押し目買い)を、注文カードの対象から外しますか　はずすが、記録はつけておいて」
        self.assertIn('window.ORDER_CARD_NO_RULES = ["R4"];', self.block)
        self.assertIn('!window.ORDER_CARD_NO_RULES.includes(String(s.rule))', self.block)
        self.assertIn('&& !window.ORDER_CARD_NO_RULES.includes(String(r.rule)) && Date.now()', self.block)

    def test_short_warning(self):
        # OWNER 2026-11-05 「制度信用でうれないと注意喚起して」
        self.assertIn('k === "貸借銘柄" ? "" : k ? "制度信用では売れません（"', self.block)
        self.assertIn('"貸借か確認できません。楽天の画面で確認"', self.block)
        self.assertEqual(self.block.count("!buy && window.marginNote(s.ticker)"), 3)
        self.assertIn('window.marginNote?.(x.ticker)', HTML)
        gw = (Path(__file__).resolve().parents[1] / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/margin_kind.json') {", gw)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-margin-kind-v1'", gw)

    def test_old_signals_are_not_listed(self):
        # OWNER 2026-11-05 「古くなったのはみえなくてよい」
        self.assertIn('< window.ORDER_CARD_TTL_MS).slice(0, 20);', self.block)

    def test_valid_card_stands_out(self):
        # OWNER 2026-11-05 「これも、有効な場合はもっとわかりやすく」
        self.assertIn("<span class='ob-valid'>有効 あと", self.block)
        self.assertIn("<span class='ol-valid'>有効 あと", self.block)
        self.assertIn('(left > 0 ? " ob-live" : " ob-old")', self.block)
        self.assertIn(".ob-live.ob-long{border-color:var(--cc-long)", HTML)

    def test_expected_yen(self):
        # OWNER 2026-11-05 「1回あたり平均で約+1,000円です。これいれて」
        self.assertIn('"1回あたり平均で約" + (y >= 0 ? "+" : "−")', self.block)
        self.assertEqual(self.block.count("window.orderCardEvYen(s, lim, qty) ?"), 3)

    def test_old_cards_leave(self):
        # OWNER 2026-11-05 「古くなったのはみえなくてよい」「おれは、ここをなおしたいの」
        self.assertIn('if (!(Date.now() - at < window.ORDER_CARD_TTL_MS)) return;', self.block)
        self.assertNotIn('!v.pinned', self.block)

    def test_virtual_day_line(self):
        # OWNER 2026-11-05 「仮想売買の今日の損益を、注目の上に1行で出して」
        block = HTML.split("「仮想売買の今日の損益を、注目の上に1行で出して。", 1)[1].split("})();", 1)[0]
        for text in ("デイ", "オーバーナイト", "スイング", "長期", "−3万到達 ", "そこから", "参考：−3万で止めていたら ", 'box.insertAdjacentElement("beforebegin",el)'):
            self.assertIn(text, block)
        self.assertIn('(over?" over":total>0?" plus":"")', block)                  # 「プラスの場合は緑」
        self.assertIn('fetch("/hold_track.json?t="+Date.now()', block)
        for banned in ("cockpitSpeak", "RssOrder"):
            self.assertNotIn(banned, block)
        js = (Path(__file__).resolve().parents[1] / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn("window.cockpitVirtualDay={at:Date.now()", js)
        # OWNER 2026-11-05 「−3万の制限なしで全部数える』に直して」「11/5までの日は旧ルールの数字だと分かるようにする」
        self.assertIn("−3万の制限なしで全部数える", js)
        self.assertIn("(o.limit_reference?'':'・旧ルール')", js)   # 「旧ルールの印は日付でなく、記録に『止めていたら』の数字が無い日にだけ」
        self.assertIn("（止めていたら ", js)
        self.assertNotIn("上限で停止", js)

    def test_overnight_exit_at_1400(self):
        # OWNER 2026-11-05 「持ち越しは翌日14:00の値段を仮想の手じまいとして確定に入れて、注目の上の1行にも足す。OVERNIGHT 5の持ち越し成績も14:00で計算する」
        self.assertIn('g("オーバーナイト",v.onDone||0,v.onOpen)', HTML)
        self.assertIn('const done=v.dayDone+(v.onDone||0)+sw.done+lg.done', HTML)
        root = Path(__file__).resolve().parents[1]
        self.assertIn("overnight_closed", (root / "trade_control.js").read_text(encoding="utf-8"))
        col = (root / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
        # OWNER 2026-11-05 「『当日15:30終値から翌取引日14:00の値段まで（14:00の値段が無い日は終値）』に直して。画面とCollectorの両方」
        for text in (HTML, col):
            self.assertIn("当日15:30終値から翌取引日14:00の値段まで（14:00の値段が無い日は終値）", text)
            self.assertNotIn("翌取引日15:30終値まで", text)
        self.assertIn('"overnight_hold_1400.json"', col)
        self.assertIn("$retClose=($exit1400/$entry-1)*100", col)
        self.assertIn("$retClose=($entry/$exit1400-1)*100", col)

    def test_real_guard_is_display_only(self):
        # OWNER 2026-11-05 「まずは２と３」：両建ての警告と、新しく入る時のその日の負けの残り枠
        self.assertIn("window.realGuardRoom = g => g.done + Math.min(g.open, 0) - g.limit", HTML)
        self.assertIn("window.realGuardCardHtml(s.ticker, buy)", HTML)
        self.assertIn("両建て中", HTML)
        src = (Path(__file__).resolve().parents[1] / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn("window.cockpitRealGuard=acct?", src)
        self.assertIn("hedged:Object.values(by).filter(g=>g.long>0&&g.short>0)", src)
        # OWNER 2026-11-05 「負けの残り枠は、今日入った信用の建玉だけで計算して…」「含み損が1回−1万円に届いたら、赤い帯と声で『損切り』と言い続ける見張り」
        self.assertIn("done:marginDone,open:sum(margin.filter(isToday))", src)
        self.assertIn("gNum(x.pnl)<=-10000", src)
        self.assertIn("別枠 持ち越し含み", HTML)
        self.assertIn('"stop-loss-band"', HTML)
        col = (Path(__file__).resolve().parents[1] / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('Invoke-SerializedSpeak $speaker "損切り"', col)
        self.assertIn("[double]$_.pnl -le -10000", col)
        # OWNER 2026-11-05 「両建て中の銘柄の建玉は声を止めて赤い帯だけにして」
        self.assertIn("-not ($slShort -contains [string]$_.code -and $slLong -contains [string]$_.code)", col)
        self.assertIn("（両建て・声なし）", HTML)

    def test_copy_buttons(self):
        for label in ('["コード",', '["指値", lim]', '["利確", tp]', '["損切り", sl]'):
            self.assertIn(label, self.block)
        self.assertIn('box.addEventListener("click", window.orderCardCopy)', self.block)


if __name__ == "__main__":
    unittest.main()
