"""Manual Grok notes (OWNER 2026-10-23): parse, expiry, Brain flags, logging, wiring. Synthetic only."""
from datetime import datetime, timedelta, timezone
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts import v10_brain_core as brain
from scripts import v10_grok_manual as grok
from tests.test_v10_brain_core import SHADOW, TABLE, live, target

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 22, 0, 30, tzinfo=timezone.utc)  # 09:30 JST
NOTE = """前置きの文
GROK_NOTE_V1
as_of: 2026-10-22 07:40
A | 悪材料 | 大口顧客が発注延期との報道 | https://example.com/a
D | 好材料 | 新製品の受注 | https://example.com/d https://example.com/d2
B | 話題 | 出典なし |
C | 速報 | 種類が違う | https://example.com/c
12345 | 噂 | コードが長い | https://example.com/x
9999 | 噂 | 監視外の銘柄 | http://insecure.example.com https://example.com/9
END
"""


class Parse(unittest.TestCase):
    def test_rows_need_code_stance_summary_and_https_source(self):
        note = grok.parse_note(NOTE.replace("A |", "123A |").replace("D |", "456D |"), now=NOW)
        self.assertTrue(note["ok"])
        self.assertEqual([(x["code"], x["stance"]) for x in note["items"]], [("123A", "悪材料"), ("456D", "好材料"), ("9999", "噂")])
        self.assertEqual(note["items"][2]["sources"], ["https://example.com/9"])           # http is dropped
        self.assertEqual(len(note["rejected"]), 3)
        self.assertEqual(note["valid_until"], "2026-10-22T15:40:00+09:00")                  # 8 hours

    def test_format_future_and_expiry(self):
        self.assertFalse(grok.parse_note("285A | 好材料 | x | https://e.com", now=NOW)["ok"])
        self.assertFalse(grok.parse_note("GROK_NOTE_V1\n285A | 好材料 | x | https://e.com\nEND", now=NOW)["ok"])
        future = NOTE.replace("07:40", "09:50")
        self.assertIn("未来", grok.parse_note(future, now=NOW)["reason"])
        late = grok.parse_note(NOTE.replace("A |", "123A |"), now=NOW + timedelta(hours=7))
        self.assertTrue(late["expired"])


class Wiring(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v10-grok-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "grok_inbox").mkdir()
        (self.tmp / "grok_inbox" / "grok_20261022_074000.txt").write_text(
            NOTE.replace("A |", "123A |").replace("D |", "456D |"), encoding="utf-8")

    def test_load_logs_once_and_feeds_the_brain_as_a_flag_only(self):
        known = {"123A": "名A", "456D": "名D"}
        logged = set()
        got = grok.load_notes(self.tmp, now=NOW, known=known, logged=logged)
        again = grok.load_notes(self.tmp, now=NOW, known=known, logged=set())   # dedupe survives a restart
        self.assertEqual(sorted(got["attention"]), ["123A", "456D"])               # 9999 is outside the universe
        self.assertEqual(again["attention"], got["attention"])
        with open(self.tmp / "records" / "2026-10-22" / grok.NOTES_FILE, newline="", encoding="utf-8-sig") as f:
            self.assertEqual(len(list(csv.DictReader(f))), 3)
        self.assertFalse(got["view"]["notes"][0]["items"][2]["in_universe"])
        rows = [target("123A.T"), target("456D.T")]
        plain = brain.pick(live(rows), ev_table=TABLE, rule_shadow=SHADOW, now=NOW)
        view = brain.pick(live(rows), ev_table=TABLE, rule_shadow=SHADOW, now=NOW, attention=got["attention"])
        self.assertEqual([p["score_pct"] for p in view["picks"]], [p["score_pct"] for p in plain["picks"]])   # no score change
        flags = {p["ticker"]: p["flags"] for p in view["picks"]}
        self.assertIn("Grok（手動）：悪材料「大口顧客が発注延期との報道」（サインと逆向き・注意）", flags["123A.T"])
        self.assertIn("Grok（手動）：好材料「新製品の受注」", flags["456D.T"])
        self.assertFalse(any("専門AIが先回り監視中" in f for f in flags["123A.T"]))
        expired = grok.load_notes(self.tmp, now=NOW + timedelta(hours=7), known=known)
        self.assertEqual((expired["attention"], expired["view"]["notes"]), ({}, []))

    def test_observer_pins_and_passes_the_notes(self):
        spec = importlib.util.spec_from_file_location("obs_grok_under_test", ROOT / "scripts" / "ai_brain_observer.py")
        obs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(obs)
        name, pin = obs.GROK_MODULE
        self.assertEqual(obs.git_blob_sha1((ROOT / "scripts" / (name + ".py")).read_bytes()), pin)
        (self.tmp / "signal_ev_table_v1.json").write_text(json.dumps(TABLE), encoding="utf-8")
        (self.tmp / "rule_shadow_v1.json").write_text(json.dumps(SHADOW, ensure_ascii=False), encoding="utf-8")
        path = self.tmp / "live_ms2.json"
        path.write_text(json.dumps(live([target("123A.T")]), ensure_ascii=False), encoding="utf-8")
        obs.brain_core_pass({}, path, now=NOW)
        view = json.loads((self.tmp / "brain_pick_v1.json").read_text("utf-8"))
        self.assertEqual(view["grok"]["notes"][0]["items"][0]["code"], "123A")
        self.assertEqual(view["specialist_watch"][0]["roles"], ["grok"])
        self.assertFalse(view["real_submit_allowed"])

    def test_check_command_and_screen(self):
        out = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "v10_grok_manual.py"), "--check",
                              str(self.tmp / "grok_inbox" / "grok_20261022_074000.txt")], capture_output=True)
        text = out.stdout.decode("utf-8")
        self.assertIn("使わなかった行", text)   # three rows are refused (the note is expired by today's clock)
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('<div id="grok-rows"></div>', html)
        self.assertIn("renderGrok();", html)
        ps = (ROOT / "downloads" / "GROK_TO_COCKPIT_V10.ps1").read_bytes()
        self.assertTrue(all(b < 128 for b in ps))
        self.assertIn(b"Remove-Item -LiteralPath $path", ps)   # an unusable answer is not kept
        self.assertNotIn(b"Invoke-WebRequest", ps)


if __name__ == "__main__":
    unittest.main()
