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


if __name__ == "__main__":
    unittest.main()
