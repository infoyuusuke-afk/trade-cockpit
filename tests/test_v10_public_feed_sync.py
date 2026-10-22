"""OWNER 2026-10-23 「キオクシアの予測チャートが直ってない」: fresh copies of the public analysis
JSON from main for the local V10 screen. Synthetic fetches only; no network."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


feed = _load("v10_public_feed_sync_test", "scripts/v10_public_feed_sync.py")
obs = _load("ai_brain_observer_feed_test", "scripts/ai_brain_observer.py")


class Sync(unittest.TestCase):
    def test_valid_files_replace_and_bad_ones_keep_the_previous_copy(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "public_feed"
            target.mkdir()
            (target / "world_market.json").write_text('{"old": true}', encoding="utf-8")

            def fetch(url):
                name = url.rsplit("/", 1)[1]
                if name == "world_market.json":
                    return b"not json"
                if name == "signals.json":
                    raise OSError("network")
                if name == "earnings_calendar.json":
                    return b"[" + b"1," * feed.MAX_BYTES + b"1]"
                return json.dumps({"name": name}).encode()
            meta = feed.sync(target, fetch=fetch)
            self.assertEqual(json.loads((target / "kioxia_5m_calendar.json").read_text("utf-8")), {"name": "kioxia_5m_calendar.json"})
            self.assertEqual((target / "world_market.json").read_text("utf-8"), '{"old": true}')   # kept
            self.assertFalse((target / "signals.json").exists())
            self.assertFalse((target / "earnings_calendar.json").exists())
            self.assertFalse(meta["files"]["world_market.json"]["ok"])
            self.assertEqual(meta["files"]["earnings_calendar.json"]["reason"], "TOO_LARGE")
            self.assertTrue(meta["files"]["kioxia_5m_calendar.json"]["ok"])
            self.assertFalse(meta["real_submit_allowed"])
            self.assertTrue((target / feed.META_FILE).exists())
            self.assertEqual(list(target.glob("*.tmp")), [])

    def test_only_public_main_files(self):
        self.assertTrue(feed.BASE_URL.startswith("https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/"))
        self.assertIn("kioxia_5m_calendar.json", feed.FEED_FILES)


class RegimeSummary(unittest.TestCase):
    """OWNER 2026-10-23: daily 地合い判定 for the 検証・除外 tab (reference only)."""

    def idx(self, price, ma20, ma60, chg):
        return {"ok": True, "price": price, "ma20": ma20, "ma60": ma60, "change_pct": chg}

    def test_verdict_strong_weak_neutral(self):
        up = {"日経平均": self.idx(110, 100, 90, 1.0), "TOPIX": self.idx(110, 100, 90, 1.0),
              "NASDAQ": {"change_pct": 1.0}, "SOX": {"change_pct": 1.0}, "VIX": {"change_pct": -6}}
        self.assertEqual(feed.regime_verdict(up)["label"], "強い")
        down = {"日経平均": self.idx(90, 100, 110, -1.0), "TOPIX": self.idx(90, 100, 110, -1.0),
                "NASDAQ": {"change_pct": -1.0}, "SOX": {"change_pct": -1.0}, "VIX": {"change_pct": 6}}
        v = feed.regime_verdict(down)
        self.assertEqual((v["label"], v["score"]), ("弱い", -9))   # 6 Japan parts, NASDAQ, SOX, VIX
        self.assertEqual(feed.regime_verdict({})["label"], "中立")
        flat = {"日経平均": self.idx(100, 100, 100, 0.1)}
        self.assertEqual(feed.regime_verdict(flat)["status"], "REFERENCE_DAILY_NOT_A_GATE")

    def test_summary_keeps_only_valid_indices_and_top5_themes(self):
        data = {"updated_at": "u", "phase": "p",
                "indices": {"日経平均": dict(self.idx(1, 1, 1, 0), ret5=2), "TOPIX": {"ok": False, "price": 9},
                            "NASDAQ": {"ok": True, "price": "x"}},
                "themes": [["T%d" % i, i, 1, [["A", 1.0, 2.0]]] for i in range(7)] + [["bad"]]}
        s = feed.summarize(data)
        self.assertEqual(list(s["indices"]), ["日経平均", "NASDAQ"])
        self.assertIsNone(s["indices"]["NASDAQ"]["price"])        # non-numbers are dropped, never invented
        self.assertEqual(len(s["themes"]), 5)
        self.assertFalse(s["real_submit_allowed"])

    def test_sync_writes_the_summary_and_keeps_it_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "public_feed"
            good = json.dumps({"indices": {"日経平均": self.idx(1, 1, 1, 0)}, "themes": []}).encode()
            feed.sync(target, fetch=lambda url: good if url.endswith("data.json") else b"{}")
            self.assertIn("日経平均", json.loads((target / feed.SUMMARY_FILE).read_text("utf-8"))["indices"])
            meta = feed.sync(target, fetch=lambda url: b"broken" if url.endswith("data.json") else b"{}")
            self.assertFalse(meta["files"][feed.SUMMARY_FILE]["ok"])
            self.assertIn("日経平均", json.loads((target / feed.SUMMARY_FILE).read_text("utf-8"))["indices"])

    def test_screen_section_is_in_the_market_tab_and_labelled_reference(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('<section id="regime-summary" class="card wide"><h2>地合い判定（日次・参考）</h2>', html)
        self.assertIn('fetch("market_summary.json?t="', html)
        self.assertIn("場中の売買サイン・安全ゲート・ブレインの点数・音声には使いません", html)


class Wiring(unittest.TestCase):
    def test_observer_pin_matches_and_runs_in_the_background(self):
        name, pin = obs.PUBLIC_FEED_MODULE
        self.assertEqual(obs.git_blob_sha1((ROOT / "scripts" / (name + ".py")).read_bytes()), pin)
        source = (ROOT / "scripts" / "ai_brain_observer.py").read_text(encoding="utf-8")
        self.assertIn('threading.Thread(target=run, name="public-feed", daemon=True)', source)
        self.assertIn("public_feed_pass(feed_state, live)", source)

    def test_gateway_serves_only_the_listed_files_from_the_feed(self):
        text = GATEWAY.read_text(encoding="utf-8-sig")
        listed = re.findall(r"'([a-z0-9_]+\.json)'", text[text.index("$publicFeedFiles = @("):text.index("if ($RuntimeDir -and $publicFeedFiles")])
        self.assertEqual(sorted(listed), sorted(feed.FEED_FILES + (feed.SUMMARY_FILE,)))
        self.assertIn("($feedItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0", text)
        allowed = text[text.index("$allowedUiFiles = @("):text.index("if ($allowedUiFiles -cnotcontains $relative)")]
        for name in feed.FEED_FILES + (feed.SUMMARY_FILE,):   # each served name is on the allow-list
            self.assertIn("'" + name + "'", allowed)


import re  # noqa: E402

if __name__ == "__main__":
    unittest.main()
