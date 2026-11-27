"""Today's realized P&L from the Rakuten CSV (OWNER 2026-11-02 「楽天のCSVで確定損益を出す形にする」). Synthetic CSVs only."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts import v10_realized_csv as rc

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 2, 20, 30, tzinfo=JST)
HEAD = "約定日,受渡日,銘柄コード,銘柄名,口座,信用区分,取引,数量[株],売却/決済単価[円],売却/決済額[円],平均取得価額[円],実現損益[円]"
ROWS = [
    '"2026/11/02","2026/11/05","1111","テストA","特定","制度","売埋","100","1,010","101,000","1,000","+1,000"',
    '"2026/11/02","2026/11/05","1111","テストA","特定","制度","売埋","100","990","99,000","1,000","-1,050"',
    '"2026/11/02","2026/11/05","2222","テストB","特定","制度","買埋","100","2,000","200,000","2,030","+2,980"',
    '"2026/11/02","2026/11/05","3333","テストC","特定","","売付","100","500","50,000","510","-1,000"',
    '"2026/11/02","2026/11/05","4444","テストD","特定","","現引","100","0","0","0","-30"',
    '"2026/10/31","2026/11/04","1111","テストA","特定","制度","売埋","100","1,000","100,000","900","+10,000"',
]


def write(folder, name, rows, enc="cp932", mtime=None):
    p = Path(folder) / name
    p.write_bytes(("\r\n".join([HEAD] + rows) + "\r\n").encode(enc))
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


class RealizedCsv(unittest.TestCase):
    def setUp(self):
        self.rt = Path(tempfile.mkdtemp())
        self.csv = Path(tempfile.mkdtemp())
        (self.rt / rc.CONFIG_FILE).write_text(json.dumps({"folder": str(self.csv)}), encoding="utf-8")

    def test_today_rows_summed_with_rakuten_numbers(self):
        write(self.csv, "realized_pl(JP)_20261102_203000.csv", ROWS)
        v = rc.build(self.rt, now=NOW)
        self.assertEqual(v["state"], "OK")
        self.assertEqual((v["yen"], v["n"]), (1000 - 1050 + 2980 - 1000 - 30, 5))   # the 10/31 row is not today
        self.assertEqual(v["long"], {"yen": -1050, "n": 3})                          # 売埋 and 売付
        self.assertEqual(v["short"], {"yen": 2980, "n": 1})                          # 買埋
        self.assertEqual(v["other"], {"yen": -30, "n": 1})
        self.assertIs(v["real_submit_allowed"], False)
        self.assertIs(v["trade_instruction"], False)
        saved = json.loads((self.rt / rc.OUT_FILE).read_text(encoding="utf-8"))
        self.assertEqual(saved["yen"], v["yen"])
        text = json.dumps(saved, ensure_ascii=False)
        for secret in ("テストA", "1111", "101,000", "1,010"):                       # no names, codes or prices are kept
            self.assertNotIn(secret, text)

    def test_newest_csv_wins_and_utf8_works(self):
        write(self.csv, "realized_pl(JP)_20261102_150000.csv", ROWS[:1], mtime=1_790_000_000)
        write(self.csv, "realized_pl(JP)_20261102_203000.csv", ROWS[:2], enc="utf-8-sig", mtime=1_790_001_000)
        write(self.csv, "realized_pl(US)_20261102_203000.csv", ROWS, mtime=1_790_002_000)   # other markets are not read
        v = rc.build(self.rt, now=NOW)
        self.assertEqual((v["state"], v["yen"], v["n"]), ("OK", -50, 2))

    def test_states(self):
        self.assertEqual(rc.build(self.rt, now=NOW)["state"], "NO_CSV")
        write(self.csv, "realized_pl(JP)_20261031.csv", ROWS[5:], mtime=NOW.timestamp() - 2 * 86400)
        self.assertEqual(rc.build(self.rt, now=NOW)["state"], "CSV_OLD")
        (self.rt / rc.CONFIG_FILE).unlink()
        self.assertEqual(rc.build(self.rt, now=NOW)["state"], "NOT_CONFIGURED")
        (self.rt / rc.CONFIG_FILE).write_text(json.dumps({"folder": str(self.csv / "none")}), encoding="utf-8")
        self.assertEqual(rc.build(self.rt, now=NOW)["state"], "FOLDER_MISSING")

    def test_unknown_format(self):
        (self.csv / "realized_pl(JP)_x.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        self.assertEqual(rc.build(self.rt, now=NOW)["state"], "FORMAT_UNKNOWN")


class Wiring(unittest.TestCase):
    def test_observer_gateway_and_card(self):
        import scripts.ai_brain_observer as obs
        name, pin = obs.REALIZED_CSV_MODULE
        self.assertEqual(obs.git_blob_sha1((ROOT / "scripts" / (name + ".py")).read_bytes()), pin)
        self.assertIn("realized_csv_pass(realized_state, live)", (ROOT / "scripts" / "ai_brain_observer.py").read_text(encoding="utf-8"))
        gw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/realized_csv.json') {", gw)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-realized-csv-v1'", gw)
        js = (ROOT / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn('gJson("/realized_csv.json")', js)
        self.assertIn('gTile("実口座 今日の確定損益（楽天CSV）",gYen(rcsv.yen)', js)
        self.assertIn('rcsv.state==="OK"', js)
        self.assertIn("手数料なしの概算・楽天の数字とずれます", js)                  # the estimate stays only as a fallback

    def test_observer_pass_once_a_minute(self):
        import scripts.ai_brain_observer as obs
        rt = Path(tempfile.mkdtemp())
        st, out = {}, io.StringIO()
        with contextlib.redirect_stdout(out):
            first = obs.realized_csv_pass(st, rt / "live.json", now=NOW)
            again = obs.realized_csv_pass(st, rt / "live.json", now=NOW + timedelta(seconds=30))
        self.assertEqual(first, {"realized_csv": "NOT_CONFIGURED", "real_submit_allowed": False})
        self.assertIsNone(again)
        self.assertTrue((rt / rc.OUT_FILE).exists())


if __name__ == "__main__":
    unittest.main()
