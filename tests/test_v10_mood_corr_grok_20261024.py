"""OWNER 2026-10-24 「地合い判定の表示、相関の仕組みの直し、Grokの答えをコクピットで読む機能」. Synthetic data only."""
import importlib.util
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("feed", ROOT / "scripts" / "v10_public_feed_sync.py")
feed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feed)
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class MoodSummary(unittest.TestCase):
    def test_yield_in_points_and_after_close_edition(self):
        d = {"updated_at": "2026-10-23 21:01:05 JST", "phase": "引け前持ち越し15:00版",
             "indices": {"米10年金利": {"ok": True, "price": 4.95, "change_pct": -3.75, "ret5": -2.0, "ma20": 5.1, "ma60": 5.0},
                         "日経平均": {"ok": True, "price": 62693.16, "change_pct": -0.34}}}
        s = feed.summarize(d)
        self.assertEqual(s["phase"], "大引け後版（21:01作成）")
        y = s["indices"]["米10年金利"]
        self.assertEqual((y["unit"], y["change_pt"], y["from_ma20_pt"]), ("yield", -0.19, -0.15))
        self.assertNotIn("unit", s["indices"]["日経平均"])
        self.assertEqual(feed.edition_name("引け前持ち越し15:00版", "2026-10-23 14:46:00 JST"), "引け前持ち越し15:00版")
        self.assertIn('x.unit === "yield"', HTML)
        self.assertIn('pt(x.change_pt)', HTML)


class GrokBots(unittest.TestCase):
    def test_latest_answer_per_bot_and_2go_cards(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "brain"
            (root / "Grok2号").mkdir(parents=True)
            (root / "Grok1号").mkdir()
            old = root / "Grok2号" / "好決算監視_20261023_0500.txt"
            old.write_text("GROK2_EARNINGS_V1\nold\nEND\n", encoding="utf-8")
            os.utime(old, (time.time() - 7200, time.time() - 7200))
            (root / "Grok2号" / "好決算監視_20261024_0500.txt").write_text(
                "GROK2_EARNINGS_V1\n対象数：2\n---\n銘柄：大末建設（1814）\n判断案：押し目の買い候補\n自信：中\n\n"
                "銘柄：ローツェ（6323）\n判断案：空売り候補（出尽くし）\n目安の価格帯：なし\n自信：低\nEND\n", encoding="utf-8")
            v = feed.grok_bots_view(root)
            two = v["bots"][1]
            self.assertEqual(two["file"], "好決算監視_20261024_0500.txt")
            self.assertEqual([(c["銘柄"], c["判断案"]) for c in two["cards"]],
                             [("大末建設（1814）", "押し目の買い候補"), ("ローツェ（6323）", "空売り候補（出尽くし）")])
            self.assertIsNone(v["bots"][0]["file"])
            self.assertFalse(v["real_submit_allowed"])
            target = Path(d) / "feed"
            meta = feed.sync(target, fetch=lambda url: (_ for _ in ()).throw(OSError("offline")),
                             now=datetime.now(timezone.utc), grok_root=root)
            self.assertTrue(meta["files"][feed.GROK_FILE]["ok"])
            self.assertEqual(len(json.loads((target / feed.GROK_FILE).read_text(encoding="utf-8"))["bots"]), 3)
            meta = feed.sync(target, fetch=lambda url: (_ for _ in ()).throw(OSError("offline")),
                             now=datetime.now(timezone.utc), grok_root=Path(d) / "missing")
            self.assertEqual(meta["files"][feed.GROK_FILE], {"ok": False, "reason": "NO_GROK_FOLDER"})

    def test_2go_badge_is_short_and_note_below(self):
        # OWNER 2026-10-26 「文字がきれてるとこある」
        self.assertIn("e(String(c[\"判断案\"] || \"—\").split(\"（\")[0])", HTML)
        self.assertIn("<div class='g2-note'>", HTML)
        self.assertIn("#grok-bots-body .cc-head .cc-badge{max-width:55%;white-space:normal", HTML)

    def test_screen_and_gateway(self):
        self.assertIn('id="grok-bots-body"', HTML)
        self.assertIn('fetch("grok_bots.json?t="', HTML)
        self.assertIn("e(b.text)", HTML)    # the answer text is escaped
        gw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertEqual(gw.count("'accumulation_watch.json', 'grok_bots.json')"), 2)


class Correlations(unittest.TestCase):
    def test_gap_view_shown(self):
        self.assertIn("米国の前日 → 東京の寄り（窓）の確かめ", HTML)
        self.assertIn("x.gap_test.big_same_dir_pct", HTML)
        self.assertIn("使わなくした関係", HTML)
        # the explanation below the table matches the rebuild (no Nintendo rotation rule)
        self.assertIn("2　寄った後には使わない", HTML)
        self.assertNotIn("キオクシア―任天堂は固定ルールではありません", HTML)
        self.assertNotIn("任天堂など逆相関候補", HTML)


class BrainLamp(unittest.TestCase):
    def test_one_lamp_details_folded(self):
        # OWNER 2026-10-24 「ブレインが正常稼働しているかのステータスランプがほしい　この表示はおれにはいらない」
        self.assertIn('id="brain-lamp"', HTML)
        self.assertIn('<details class="brain-detail"><summary>詳しい状態（調べる時だけ）</summary>', HTML)
        for word in ('"正常に動いています"', '"止まっています"', '"一時停止中"', '"場中なのに値段が止まっています"'):
            self.assertIn(word, HTML)
        self.assertIn('if(ex.real_submit_allowed!==false)down.push(', HTML)
        # OWNER 2026-10-26 「特別気配の直し」: stocks with no price yet are named on a yellow lamp
        self.assertIn('rt.availability?.quote_pending_sample', HTML)
        self.assertIn('"動いています（値待ちあり）","特別気配など値がまだない "', HTML)


class FreshnessLamps(unittest.TestCase):
    def test_gpt_and_grok_lamps(self):
        # OWNER 2026-10-24 「専門アナリストも同様…最新情報なのか過去情報なのかわからないとこわい」「グロックも同様」
        self.assertIn('<div id="agent-lamp"></div>', HTML)
        self.assertIn('<div id="grok-lamp"></div>', HTML)
        for word in ('"最新","今日 "', '"前の答え"', '"届いていません"', '"休日"'):
            self.assertIn(word, HTML)
        self.assertIn("実行日時：", HTML)              # Grok lamps use the answer's own run time
        self.assertIn('["red", "古い"', HTML)
        # OWNER 2026-10-26: a 1号 answer without 実行日時 is timed from its own 「（YYYY-MM-DD HH:MM JST）」
        self.assertIn(r"|| /[（(](\d{4}-\d{2}-\d{2} \d{2}:\d{2}) JST[）)]/.exec(b.text", HTML)


class GptCards(unittest.TestCase):
    def test_gpt_answers_as_cards(self):
        # OWNER 2026-10-26 「カードタイプにして直観的に理解できる表示にして」
        self.assertIn('const gptCard=(role,x)=>{', HTML)
        self.assertIn('<div class="gpt-cond go"><b>注目</b>', HTML)
        self.assertIn('<div class="gpt-cond stop"><b>無効</b>', HTML)
        # OWNER 2026-10-26 「コードと名前を大きく、PRE-NEXTか需給かの札、何があったか1行、注目する条件を緑・無効になる条件を灰色…
        # 需給は買残・売残・倍率を数字で並べて」
        for part in ('<span class="gpt-code">', '<span class="gpt-name">', 'gpt-role-badge', '<div class="gpt-what">',
                     '<div class="gpt-supply"><span>買残<b', '<span>売残<b', '<span>倍率<b'):
            self.assertIn(part, HTML)
        self.assertIn(".gpt-card .gpt-cond.stop{background:#1b1c20;border:1px solid #3a3b40", HTML)
        self.assertIn('rel="noopener noreferrer"', HTML)
        self.assertIn("'<h3>GPTタスクの答え（自動・ChatGPTアプリ）</h3><div class=\"scalp-strip gpt-cards\">'", HTML)


class OrderCard(unittest.TestCase):
    def test_reference_only_card_never_orders(self):
        # OWNER 2026-10-24 「注文カード作成。検証中と表示し、成績が出るまでは参考のみ　俺が確認して執行おす」
        self.assertIn("検証中：成績が出るまで参考のみ。確認してから自分で執行してください（このカードは注文を出しません）", HTML)
        self.assertIn('window.ORDER_CARD_CODES = ["285A.T"];', HTML)
        self.assertIn("b.real_submit_allowed === false && Number.isFinite(gen) && Date.now() - gen < window.ORDER_CARD_TTL_MS", HTML)
        block = HTML[HTML.index("window.ORDER_CARD_CODES"):HTML.index('window.loadGrokBots = () =>')]
        for word in ("RssMarginOpenOrder", "RssStockOrder", "method:\"POST\"", "method: \"POST\"", "/order"):
            self.assertNotIn(word, block)


class GrokOnEarningsCalendar(unittest.TestCase):
    def test_tags_per_code(self):
        # OWNER 2026-10-24 「決算日程にGrokをつなぐ」
        two = "\n".join(["GROK2_EARNINGS_V1", "実行日時：2026-10-24 05:00", ""])
        three = "\n".join(["GROK3_PREVIEW_V1", "実行日時：2026-10-27 17:30", "---", "銘柄：キオクシアHD（285A）",
                           "事前の空気：警戒（下げて悲観）", "---",
                           "決算のあとの答え合わせ：アドバンテスト（6857）／結果 上振れ／事前の空気 期待先行 → 外れ", "END"])
        bots = [{"bot": "Grok2号", "text": two, "cards": [{"銘柄": "大末建設（1814）", "判断案": "押し目の買い候補"}]},
                {"bot": "Grok3号", "cards": [], "text": three}]
        tags = feed.grok_tags(bots)
        self.assertEqual(tags["1814"], [{"bot": "2号", "kind": "決算後", "label": "押し目の買い候補", "day": "10/24"}])
        self.assertEqual(tags["285A"], [{"bot": "3号", "kind": "決算前", "label": "警戒", "day": "10/27"}])
        self.assertEqual(tags["6857"], [{"bot": "3号", "kind": "答え合わせ", "label": "外れ", "day": "10/27"}])

    def test_calendar_decoration_and_no_summary_boxes(self):
        self.assertIn("window.decorateEarningsWithGrok = () =>", HTML)
        # the per-tab boxes are now shown on CONTROL only (OWNER 2026-10-24 「タブの箱を外す」)
        self.assertIn('.tab-pane:not([data-pane="control"]) > .cc-tab-owner-summary{display:none!important}', HTML)
        js = (ROOT / "earnings-calendar.js").read_text(encoding="utf-8")
        self.assertNotIn("grok", js.lower())          # the pinned calendar script is unchanged


class Grok3Cards(unittest.TestCase):
    def test_score_and_change_from_previous(self):
        # OWNER 2026-10-24 「カードタイプで点数バロメーター付きで日々の上下が一目でわかるようにして」
        def answer(day, mood, x, broker):
            return chr(10).join(["GROK3_PREVIEW_V1", "実行日時：2026-10-%s 17:30" % day, "---", "銘柄：キオクシアHD（285A）／5",
                              "決算予定：2026-10-30 18:45（引け後）", "証券会社：" + broker, "Xの空気：" + x,
                              "需給と織り込み：20日 -3%", "事前の空気：" + mood, "END"])
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            first = folder / "a.txt"
            first.write_text(answer("26", "警戒（悲観）", "弱気（売り）", "見当たらず"), encoding="utf-8")
            os.utime(first, (time.time() - 3600, time.time() - 3600))
            (folder / "b.txt").write_text(answer("27", "中立（並み）", "強気（買い）", "目標株価を引き上げ"), encoding="utf-8")
            cards = feed.grok3_cards(folder)
        self.assertEqual(len(cards), 1)
        c = cards[0]
        self.assertEqual((c["code"], c["score"], c["prev_score"], c["prev_day"], c["history"]), ("285A", 2, -3, "10/26", [-3, 2]))
        self.assertIn("g3-bar", HTML)
        self.assertIn("期待の強さ：事前の空気（期待先行+2／中立0／警戒-2）", HTML)

    def test_no_score_without_mood(self):
        self.assertIsNone(feed.grok3_score({"事前の空気": "材料不足（カバーなし）"}))

    def test_broker_points(self):
        # OWNER 2026-10-24 「証券会社の点数」
        self.assertEqual(feed.grok3_broker_points("2026-10-19 GSが買い継続・目標13,350→14,900円"), 1)
        self.assertEqual(feed.grok3_broker_points("目標株価の引き下げが続いている（UBS 7,200→6,700円、7,600→7,300円）"), -1)
        self.assertEqual(feed.grok3_broker_points("目標を13,100円に引き上げ"), 1)
        self.assertEqual(feed.grok3_broker_points("10月の変更は見当たらず（直近は9,400→8,900円）"), 0)
        self.assertEqual(feed.grok3_broker_points("A 1,000→1,200円、B 2,000→1,800円"), 0)
        self.assertEqual(feed.grok3_points({"事前の空気": "警戒（悲観）", "Xの空気": "強気", "証券会社": "目標を3,200→3,600円"}),
                         {"mood": -2, "x": 1, "broker": 1})
        self.assertIn("[\"証券会社\", c.points.broker]", HTML)

    def test_checks_grouped_by_check_day(self):
        # OWNER 2026-10-24 「答え合わせ（確認日ごと）」
        def answer(day, *checks):
            return chr(10).join(["GROK3_PREVIEW_V1", "実行日時：2026-10-%s 17:30" % day, "---"] +
                                ["決算のあとの答え合わせ：" + c for c in checks] + ["END"])
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            first = folder / "a.txt"
            first.write_text(answer("28", "アドバンテスト（6857）／結果 上振れ／翌日の窓 +3.1%／事前の空気 警戒 → 外れ"), encoding="utf-8")
            os.utime(first, (time.time() - 3600, time.time() - 3600))
            (folder / "b.txt").write_text(answer("31", "キオクシアHD（285A）／結果 上振れ／翌日の窓 +5.0%／事前の空気 期待先行 → 当たり；中外製薬（4519）／結果 同じ／事前の空気 中立 → 判定不能",
                                                 "なし"), encoding="utf-8")
            checks = feed.grok3_checks(folder)
        self.assertEqual([(k["day"], k["hit"], k["miss"], k["unknown"]) for k in checks], [("10/31", 1, 0, 1), ("10/28", 0, 1, 0)])
        self.assertEqual(checks[0]["items"][0], {"code": "285A", "name": "キオクシアHD（285A）", "result": "上振れ", "gap": "+5.0%",
                                                 "mood": "期待先行", "verdict": "当たり"})
        self.assertIn("答え合わせ（確認日ごと）", HTML)


class PriceVolumeHints(unittest.TestCase):
    # OWNER 2026-10-24 「決算前の値動きと出来高のヒントをPCで計算して、3号カードの横に出して」
    def test_hint_numbers_and_labels(self):
        flat = [(100.0, 1000)] * 60
        rising = [(100.0 + i, 3000) for i in range(1, 6)]     # +5% on 3x volume
        h = feed.price_volume_hint(flat + rising, [(1000.0, 0)] * 65)
        self.assertEqual((h["ret5"], h["vol_ratio"], h["rel20"]), (5.0, 3.0, 5.0))
        self.assertEqual(h["hints"][0], {"tone": "warn", "text": "出来高を伴って上昇（期待で買われている。織り込みに注意）"})
        self.assertIsNone(feed.price_volume_hint(flat[:20]))
        quiet = feed.price_volume_hint(flat + [(100.0, 1000)] * 5)
        self.assertEqual(quiet["hints"], [{"tone": "", "text": "目立つ動きなし"}])

    def test_attach_uses_cache_and_never_breaks(self):
        calls = []

        def bars(symbol):
            calls.append(symbol)
            return [(100.0, 1000)] * 65
        view = {"bots": [{"bot": "Grok3号", "preview_cards": [{"code": "285A"}]}]}
        now = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            feed.attach_hints(view, Path(d), now, bars)
            feed.attach_hints(view, Path(d), now, bars)              # cached: no second download
            self.assertEqual(calls, ["^N225", "285A.T"])
            self.assertEqual(view["bots"][0]["preview_cards"][0]["pv"]["vol_ratio"], 1.0)
            feed.attach_hints({"bots": [{"preview_cards": [{"code": "6857"}]}]}, Path(d), now,
                              lambda s: (_ for _ in ()).throw(OSError("offline")))
        self.assertIn("値動き・出来高（PC計算 ", HTML)


class HeaderLamps(unittest.TestCase):
    def test_badge_and_verified_line(self):
        # OWNER 2026-10-24 「ランプの赤を直して」「完全照合の日付」
        self.assertIn('fetch("public_feed_meta.json?t="+Date.now()).then(r=>r.json()).then(m=>{', HTML)
        self.assertNotIn('fetch("signals.json?t="+Date.now()).then(r=>r.json()).then(d=>{\n   const badge', HTML.replace("\r\n", "\n"))
        self.assertIn("s.live_check", HTML)

    def test_live_check_copied_into_summary(self):
        def fetch(url):
            name = url.rsplit("/", 1)[1]
            if name == "live_focus.json":
                return json.dumps({"verified_count": 7, "expected_count": 10, "status": "稼働", "updated_at": "2026-10-26 10:00:00 JST",
                                   "speech_enabled": True, "rows": [{"x": 1}]}).encode()
            if name == "data.json":
                return json.dumps({"updated_at": "2026-10-26 09:55:00 JST", "indices": {}}).encode()
            raise OSError("offline")
        with tempfile.TemporaryDirectory() as d:
            feed.sync(Path(d), fetch=fetch, now=datetime(2026, 10, 26, 1, 0, tzinfo=timezone.utc), grok_root=Path(d) / "none")
            s = json.loads((Path(d) / feed.SUMMARY_FILE).read_text(encoding="utf-8"))
            self.assertFalse((Path(d) / "live_focus.json").exists())
        self.assertEqual(s["live_check"], {"verified_count": 7, "expected_count": 10, "status": "稼働", "updated_at": "2026-10-26 10:00:00 JST"})


class TradeWatchView(unittest.TestCase):
    def test_first_tab_shows_what_to_watch(self):
        # OWNER 2026-10-24 「トレード中におれが見るべきところを表示するように設定してくれ」
        self.assertIn('<button class="cockpit-tab active" data-tab="scalp">トレード中</button>', HTML)
        for part in ("<h2>トレード中に見るところ</h2>", "id='trade-brain-lamp'", "id='trade-ai-lamp'", "id='trade-watch-orders'"):
            self.assertIn(part, HTML)
        self.assertIn('const pane = document.getElementById("trade-watch-orders");', HTML)
        self.assertIn("setInterval(window.loadGrokBots, 120000)", HTML)

    def test_trade_brain_lamp_red_when_unreadable(self):
        # OWNER 2026-10-24 「トレード中タブのブレインのランプを、状態が読めない時は赤にして」
        failed = HTML[HTML.index("}).catch(()=>{\n     document.getElementById(\"brain-runtime-grid\")".replace("\n", "\r\n" if "\r\n" in HTML else "\n")):]
        failed = failed[:failed.index("});")]
        self.assertIn('tl.innerHTML=freshLamp("red","ブレイン：止まっています"', failed)


if __name__ == "__main__":
    unittest.main()
