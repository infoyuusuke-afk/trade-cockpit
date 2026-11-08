"""OWNER 2026-11-08: the morning and earnings voice. Made-up files only; no record is in the repository."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import voice_notice as v  # noqa: E402

DAY = "2026-11-09"


def setup(root):
    files, brain = Path(root, "files"), Path(root, "brain")
    (files / "public_feed").mkdir(parents=True)
    (brain / "Grok3号").mkdir(parents=True)
    cal = {"calendar": [{"code": "1111", "name": "テスト電機", "date": DAY, "watched": True},
                        {"code": "2222", "name": "テスト造船", "date": DAY, "watched": True},
                        {"code": "3333", "name": "テスト通信", "date": DAY, "watched": True},
                        {"code": "6525", "name": "ＫＯＫＵＳＡＩ　ＥＬＥＣＴＲＩＣ", "date": DAY, "watched": True},
                        {"code": "4444", "name": "テスト商事", "date": DAY, "watched": False}]}
    (files / "public_feed" / "earnings_calendar.json").write_text(json.dumps(cal, ensure_ascii=False), encoding="utf-8")
    (files / "earnings_times_v1.json").write_text(json.dumps({"stocks": {"6525": {"last_at": "2026-08-06 14:00"}}}), encoding="utf-8")
    (brain / "Grok3号" / "決算前監視_20261108_080000.txt").write_text("\n".join([
        "銘柄：テスト電機（1111）／決算の何営業日前か：1",
        "決算予定：2026-11-09 14:00（場中）／出典 https://example.com/ir",
        "銘柄：テスト造船（2222）／決算の何営業日前か：1",
        "決算予定：2026-11-09（時刻未確認・場中／引け後未確認）／出典 https://example.com/ir",
        "銘柄：テスト通信（3333）／決算の何営業日前か：1",
        "決算予定：2026-11-09 13:00（場中）／出典 二次情報",
        "銘柄：テスト商事（4444）",
        "決算予定：2026-11-09 15:30（引け後）／出典 https://example.com/ir"]), encoding="utf-8")
    return str(files), str(brain)


class Confirmed(unittest.TestCase):
    def test_only_a_time_with_a_source_counts(self):
        with tempfile.TemporaryDirectory() as root:
            files, brain = setup(root)
            got = v.confirmed_times(brain, DAY)
            self.assertEqual(got.get("1111"), "14:00")
            self.assertNotIn("2222", got)   # 時刻未確認
            self.assertNotIn("3333", got)   # no https source
            self.assertEqual(got.get("4444"), "15:30")

    def test_the_last_earnings_time_is_never_used_for_the_alert(self):
        with tempfile.TemporaryDirectory() as root:
            files, brain = setup(root)
            keys = [k for k, _ in v.due(files, brain, DAY, "13:45", set())]
            self.assertEqual(keys, ["1111-15"])   # 6525 only has the previous time, so it is not alerted

    def test_fifteen_and_five_minutes_once_each(self):
        with tempfile.TemporaryDirectory() as root:
            files, brain = setup(root)
            self.assertEqual([k for k, _ in v.due(files, brain, DAY, "13:47", set())], ["1111-15"])   # up to 2 minutes late
            self.assertEqual(v.due(files, brain, DAY, "13:48", set()), [])
            self.assertEqual(v.due(files, brain, DAY, "13:45", {"1111-15"}), [])
            self.assertEqual([k for k, _ in v.due(files, brain, DAY, "13:55", set())], ["1111-5"])

    def test_after_the_close_is_not_alerted(self):
        with tempfile.TemporaryDirectory() as root:
            files, brain = setup(root)
            self.assertEqual(v.due(files, brain, DAY, "15:15", set()), [])

    def test_an_announced_stock_is_quiet(self):
        with tempfile.TemporaryDirectory() as root:
            files, brain = setup(root)
            Path(files, "tdnet_today_v1.json").write_text(json.dumps({"date": DAY, "items": [{"code": "1111", "title": "決算短信"}]}, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(v.due(files, brain, DAY, "13:45", set()), [])


class Morning(unittest.TestCase):
    def test_the_text_reads_names_not_codes(self):
        with tempfile.TemporaryDirectory() as root:
            files, brain = setup(root)
            text = v.morning_text(files, brain, DAY)
            self.assertIn("テスト電機の決算、場中の14時。", text)
            self.assertIn("コクサイ エレクトリックの決算、時刻は未確認。前回は14時でした。", text)
            self.assertIn("時刻を確かめた銘柄だけ", text)
            for code in ("1111", "6525"):
                self.assertNotIn(code, text)
            self.assertTrue(text.endswith("売買の判断はご自身でお願いします。"))

    def test_the_script_has_no_pc_path(self):
        src = (Path(__file__).resolve().parents[1] / "scripts" / "voice_notice.py").read_text(encoding="utf-8")
        for word in ("C:\\\\", "C:/", "Users"):
            self.assertNotIn(word, src)
        self.assertNotIn("order", src.lower().replace("ordered", ""))


if __name__ == "__main__":
    unittest.main()
