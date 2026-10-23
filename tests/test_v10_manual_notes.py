"""Hand-delivered notes (OWNER 2026-10-23): Grok X topics and backup GPT analysts.
Parse, expiry, sources, backup-only rule, Brain flags (no score), 注目 rows, hit/miss scoring,
observer pin, paste button. Synthetic only; replaces the GROK_NOTE_V1 tests."""
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
from scripts import v10_manual_notes as notes
from scripts import v10_signal_ev_table as ev
from tests.test_v10_brain_core import SHADOW, TABLE, live, target

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 22, 0, 30, tzinfo=timezone.utc)  # 09:30 JST
GROK = """前置き
GROK_NOTE_V2
123A | 強 | 弱気 | 大口顧客が発注延期との報道 | https://x.com/a/status/1 | 2026-10-22 07:40
456D | 中 | 強気 | 新製品の受注 | https://example.com/d https://example.com/d2 | 2026-10-22 08:10
B | 強 | 弱気 | コードが短い | https://example.com/b | 2026-10-22 08:00
7777 | 特大 | 強気 | 強さが違う | https://example.com/c | 2026-10-22 08:00
8888 | 弱 | 強気 | 出典なし |  | 2026-10-22 08:00
9999 | 弱 | 強気 | 未来 | https://example.com/f | 2026-10-22 10:30
5555 | 弱 | 強気 | 監視外 | http://insecure.example.com https://example.com/9 | 2026-10-22 08:05
END
"""
GPT = """GPT_ANALYST_NOTE_V1
寄り前 | 123A | 監視 | 米国の半導体安 | https://example.com/p | 2026-10-22 08:20
需給 | 456D | 強気 | 信用倍率が低い | https://example.com/s | 2026-10-22 12:20
Revenue Hunter | - | 監視 | 有料記事の試験 | https://example.com/r | 2026-10-22 08:25
誰か | 123A | 強気 | 名前が違う | https://example.com/x | 2026-10-22 08:25
END
"""


class Parse(unittest.TestCase):
    def test_grok_rows_need_code_strength_view_reason_https_and_time(self):
        got = notes.parse(GROK, now=NOW)
        self.assertTrue(got["ok"])
        self.assertEqual(got["kind"], "grok")
        self.assertEqual([(x["code"], x["strength"], x["view"]) for x in got["items"]],
                         [("123A", "強", "弱気"), ("456D", "中", "強気"), ("5555", "弱", "強気")])
        self.assertEqual(got["items"][2]["sources"], ["https://example.com/9"])   # http is dropped
        self.assertEqual(len(got["rejected"]), 4)
        self.assertIn("未来", " ".join(r["reason"] for r in got["rejected"]))
        self.assertEqual(got["items"][0]["valid_until"], "2026-10-22T15:40:00+09:00")   # 8 hours

    def test_gpt_rows_and_unknown_format(self):
        got = notes.parse(GPT, now=NOW + timedelta(hours=3))
        self.assertEqual(got["kind"], "gpt")
        self.assertEqual([(x["role"], x["code"], x["view"]) for x in got["items"]],
                         [("premarket", "123A", "監視"), ("supply_sq", "456D", "強気"), ("revenue_hunter", "-", "監視")])
        self.assertEqual(len(got["rejected"]), 1)
        self.assertFalse(notes.parse("GROK_NOTE_V1\n285A | 好材料 | x | https://e.com\nEND", now=NOW)["ok"])

    def test_expired_rows_are_refused(self):
        got = notes.parse(GROK, now=NOW + timedelta(hours=7))
        self.assertNotIn("123A", [x["code"] for x in got["items"]])
        self.assertIn("期限切れ", " ".join(r["reason"] for r in got["rejected"]))


class Load(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v10-notes-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / notes.GROK_DIR).mkdir()
        (self.tmp / notes.ANALYST_DIR).mkdir()
        (self.tmp / notes.GROK_DIR / "grok_20261022_074000.txt").write_text(GROK, encoding="utf-8")
        (self.tmp / notes.ANALYST_DIR / "anything.txt").write_text(GPT, encoding="utf-8")   # any .txt in the folder
        self.known = {"123A": "名A", "456D": "名D"}

    def test_flags_only_logged_once_and_backup_only(self):
        inbox = self.tmp / "inbox"
        inbox.mkdir()
        later = NOW + timedelta(hours=3)                                          # 12:30 JST
        got = notes.load(self.tmp, now=later, known=self.known, agent_inbox=str(inbox), logged=set())
        self.assertEqual(sorted(got["analysts"]), ["premarket", "revenue_hunter", "supply_sq"])
        self.assertEqual({e["role"] for e in got["attention"]["123A"]}, {"grok", "manual_premarket"})
        # the 12:15 slot was delivered automatically: its backup rows are refused with the reason
        (inbox / "agent_research_sched_20261022_1215.json").write_text("{}", encoding="utf-8")
        got = notes.load(self.tmp, now=later, known=self.known, agent_inbox=str(inbox), logged=set())
        self.assertNotIn("supply_sq", got["analysts"])
        self.assertIn("自動のレポートが届いているので使いません", [r["reason"] for r in got["view"]["refused"]])
        with open(self.tmp / "records" / "2026-10-22" / notes.LOG_FILE, newline="", encoding="utf-8-sig") as f:
            logged = list(csv.DictReader(f))
        self.assertEqual(len(logged), 7)   # 4 Grok (9999 posted 10:30 is past by 12:30) + 3 analyst rows, once each
        rows = [target("123A.T"), target("456D.T")]
        plain = brain.pick(live(rows), ev_table=TABLE, rule_shadow=SHADOW, now=NOW)
        g = notes.load(self.tmp, now=NOW, known=self.known, agent_inbox=str(inbox))
        view = brain.pick(live(rows), ev_table=TABLE, rule_shadow=SHADOW, now=NOW, attention=g["attention"])
        self.assertEqual([p["score_pct"] for p in view["picks"]], [p["score_pct"] for p in plain["picks"]])   # no score change
        flags = {p["ticker"]: p["flags"] for p in view["picks"]}
        self.assertIn("X話題（Grok・手動）：強・弱気「大口顧客が発注延期との報道」（サインと逆向き・注意）", flags["123A.T"])
        self.assertIn("専門AIが先回り監視中（premarket・手動）", flags["123A.T"])

    def test_x_topics_in_the_attention_list(self):
        notes.load(self.tmp, now=NOW, known=self.known, logged=set())
        today = brain.today_lists(self.tmp / "records", now=NOW)
        x = [i for i in today["attention"] if i["kind"] == "XTOPIC"]
        self.assertEqual(today["x_topics_total"], len(x))
        self.assertTrue(x and x[0]["label"].startswith("X話題 "))

    def test_hit_or_miss_after_the_close(self):
        notes.load(self.tmp, now=NOW, known=self.known, logged=set())
        day = self.tmp / "records" / "2026-10-22"
        (day / "ticks.csv").write_text("captured_at,ticker,name,exchange_time,price\n" + "".join(
            "x,%s,n,%s,%s\n" % r for r in (("123A.T", "09:30:00", 1000), ("123A.T", "10:00:00", 990), ("123A.T", "10:30:00", 1010),
                                          ("123A.T", "15:29:00", 980), ("456D.T", "09:30:00", 500), ("456D.T", "15:00:00", 510))),
            encoding="utf-8-sig")
        self.assertGreater(notes.score_day(day, ev=ev), 0)
        self.assertEqual(notes.score_day(day, ev=ev), 0)                         # once a day
        with open(day / notes.OUTCOME_FILE, newline="", encoding="utf-8-sig") as f:
            got = {(r["source"], r["code"]): r for r in csv.DictReader(f)}
        a = got[("grok", "123A")]                                                # 弱気: down at 30 min and at the close
        self.assertEqual((a["hit_30m"], a["hit_60m"], a["hit_close"]), ("当たり", "外れ", "当たり"))
        self.assertEqual(got[("grok", "456D")]["hit_close"], "当たり")            # 強気 and up
        self.assertEqual(got[("gpt", "123A")]["hit_close"], "")                   # 監視 has no direction


class Wiring(unittest.TestCase):
    def test_observer_pin_and_brain_view(self):
        spec = importlib.util.spec_from_file_location("obs_notes_under_test", ROOT / "scripts" / "ai_brain_observer.py")
        obs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(obs)
        name, pin = obs.MANUAL_NOTES_MODULE
        self.assertEqual(obs.git_blob_sha1((ROOT / "scripts" / (name + ".py")).read_bytes()), pin)
        self.assertFalse((ROOT / "scripts" / "v10_grok_manual.py").exists())   # replaced by v10_manual_notes
        tmp = Path(tempfile.mkdtemp(prefix="v10-notes-obs-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / notes.GROK_DIR).mkdir()
        (tmp / notes.GROK_DIR / "g.txt").write_text(GROK, encoding="utf-8")
        (tmp / "signal_ev_table_v1.json").write_text(json.dumps(TABLE), encoding="utf-8")
        (tmp / "rule_shadow_v1.json").write_text(json.dumps(SHADOW, ensure_ascii=False), encoding="utf-8")
        path = tmp / "live_ms2.json"
        path.write_text(json.dumps(live([target("123A.T")]), ensure_ascii=False), encoding="utf-8")
        obs.brain_core_pass({}, path, now=NOW)
        view = json.loads((tmp / "brain_pick_v1.json").read_text("utf-8"))
        self.assertEqual(view["grok"]["notes"][0]["source"], "grok")
        self.assertEqual(view["specialist_watch"][0]["roles"], ["grok"])
        self.assertFalse(view["real_submit_allowed"])

    def test_check_command_screen_and_button(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "x.txt"
            f.write_text(GROK, encoding="utf-8")
            out = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "v10_manual_notes.py"), "--check", str(f)],
                                 capture_output=True).stdout.decode("utf-8")
        self.assertIn("使わなかった行", out)
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('<div id="grok-rows"></div>', html)
        self.assertIn("renderGrok();", html)
        self.assertIn("『手動』", html)
        ps = (ROOT / "downloads" / "GROK_TO_COCKPIT_V10.ps1").read_bytes()
        self.assertTrue(all(b < 128 for b in ps))
        self.assertIn(b'[ValidateSet("grok", "analyst")][string]$Kind = "grok"', ps)
        self.assertIn(b"Remove-Item -LiteralPath $path", ps)   # an unusable answer is not kept
        self.assertNotIn(b"Invoke-WebRequest", ps)
        self.assertIn(b"-Kind analyst", (ROOT / "downloads" / "ANALYST_TO_COCKPIT_V10.cmd").read_bytes())


if __name__ == "__main__":
    unittest.main()
