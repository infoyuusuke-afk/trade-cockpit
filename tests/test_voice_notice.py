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


class AuditFindings(unittest.TestCase):
    """The audit of 2026-11-08: newest answer wins, words of doubt, a stock line without a code, bad values."""

    def test_the_newest_answer_decides_for_each_stock(self):
        with tempfile.TemporaryDirectory() as root:
            files, brain = setup(root)
            Path(brain, "Grok3号", "決算前監視_20261109_080000.txt").write_text("\n".join([
                "銘柄：テスト電機（1111）",
                "決算予定：2026-11-09（時刻未確認・二次で14:00場中との記載あり）／出典 https://example.com/x"]), encoding="utf-8")
            got = v.confirmed_times(brain, DAY)
            self.assertNotIn("1111", got)          # the older 14:00 is not kept
            self.assertEqual(got.get("4444"), "15:30")   # a stock the new answer does not list keeps its time

    def test_words_of_doubt_anywhere_on_the_line(self):
        lines = ["銘柄：A社（5001）", "決算予定：2026-11-09 14:00（未確定）／出典 https://a",
                 "銘柄：B社（5002）", "決算予定：2026-11-09 14:00（前回実績から推定）／出典 https://a",
                 "銘柄：C社（5003）", "決算予定：2026-11-09 14:00（場中）／出典 https://a （会社は時刻未確認）",
                 "銘柄：D社（5004）", "決算予定：2026-11-09 14:00（場中） https://a",
                 "銘柄：E社（5005）", "決算予定：2026-11-09 13:30（場中）／出典 https://a"]
        self.assertEqual({k: x for k, x in v.read_answer(lines, DAY).items() if x}, {"5005": "13:30"})

    def test_a_stock_line_without_a_code_does_not_borrow_the_one_before(self):
        lines = ["銘柄：A社（5001）", "決算予定：2026-11-10 14:00（場中）／出典 https://a",
                 "■銘柄：B社", "決算予定：2026-11-09 13:00（場中）／出典 https://a",
                 "銘柄：C社（5003）", "決算予定：2026-11-09（時刻未確認）",
                 "決算予定：2026-11-09 12:45（場中）／出典 https://a"]
        self.assertEqual({k: x for k, x in v.read_answer(lines, DAY).items() if x}, {})

    def test_bad_minutes_and_bad_files_do_not_stop_the_watch(self):
        with tempfile.TemporaryDirectory() as root:
            files, brain = setup(root)
            Path(brain, "Grok3号", "決算前監視_20261399_080000.txt").write_text("x", encoding="utf-8")
            Path(brain, "Grok3号", "決算前監視_20261108_090000.txt").write_text(
                "銘柄：テスト通信（3333）\n決算予定：2026-11-09 14:75（場中）／出典 https://a\n", encoding="utf-8")
            Path(brain, "研究結果", "音声").mkdir(parents=True)
            Path(brain, "研究結果", "音声", "決算時刻_確認済み.json").write_text("[1]", encoding="utf-8")
            Path(files, "tdnet_today_v1.json").write_text("5", encoding="utf-8")
            self.assertEqual([k for k, _ in v.due(files, brain, DAY, "13:45", set())], ["1111-15"])

    def test_the_morning_text_stays_short_and_ends_with_the_closing_words(self):
        with tempfile.TemporaryDirectory() as root:
            files, brain = setup(root)
            ev = {"events": [{"date": DAY, "impact": "高", "time_jst": "21:30", "title": "長い題" * 100}, {"date": DAY, "impact": "高"}]}
            Path(files, "public_feed", "event_calendar.json").write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
            text = v.morning_text(files, brain, DAY)
            self.assertLessEqual(len(text), v.MAX_TEXT)
            self.assertNotIn("None", text)
            self.assertTrue(text.endswith("売買の判断はご自身でお願いします。"))

    def test_owner_decisions_of_the_second_audit(self):
        lines = ["銘柄：A社（5001）", "決算予定：2026-11-09 14:00（場中）／出典 会社IR ／ https://ir.example.com/x.php?date=20261109",
                 "銘柄：B社（5002）", "決算予定：2026-11-09 13:00（場中・二次サイト）／https://kabu.example.com/b",
                 "銘柄：C社（5003）", "決算予定：2026-11-09 12:00（昼休み）／出典 https://c",
                 "銘柄：D社（5004）／決算：2026-11-09 10:00（場中）／出典 https://d",
                 "銘柄：E社（5005）／決算：2026-11-09（時刻未確認）"]
        self.assertEqual({k: x for k, x in v.read_answer(lines, DAY).items() if x}, {"5001": "14:00", "5002": "13:00", "5003": "12:00", "5004": "10:00"})
        self.assertIn("5005", v.read_answer(lines, DAY))   # listed, so an older sure time of it is dropped

    def test_the_lunch_break_is_alerted_and_a_closed_day_is_quiet(self):
        with tempfile.TemporaryDirectory() as root:
            files, brain = setup(root)
            Path(brain, "Grok3号", "決算前監視_20261108_090000.txt").write_text(
                "銘柄：テスト電機（1111）\n決算予定：2026-11-09 12:00（昼休み）／出典 https://a\n", encoding="utf-8")
            self.assertEqual([k for k, _ in v.due(files, brain, DAY, "11:45", set())], ["1111-15"])
            self.assertIn("テスト電機の決算、昼休みの12時。", v.morning_text(files, brain, DAY))
            self.assertFalse(v.closed(files, DAY))
            ev = {"events": [{"date": DAY, "category": "休場", "title": "日本株休場／先物祝日取引あり"}]}
            Path(files, "public_feed", "event_calendar.json").write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(v.closed(files, DAY))
            self.assertTrue(v.closed(files, "2026-12-31"))
            self.assertTrue(v.closed(files, "2026-11-08"))   # Sunday

    def test_a_timeout_is_told_by_the_exit_code(self):
        src = (Path(__file__).resolve().parents[1] / "scripts" / "voice_notice.py").read_text(encoding="utf-8")
        self.assertIn("exit 3", src)
        self.assertIn("r.returncode == 3", src)
        self.assertIn("$ProgressPreference='SilentlyContinue'", src)

    def test_the_voice_is_sent_through_powershell_without_the_text_in_the_command(self):
        src = (Path(__file__).resolve().parents[1] / "scripts" / "voice_notice.py").read_text(encoding="utf-8")
        self.assertIn("Invoke-WebRequest", src)
        self.assertIn("$env:VOICE_NOTICE_URL", src)
        self.assertNotIn("urllib.request", src)


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

    def test_the_sox_cautions_are_said_first(self):
        # OWNER 2026-11-08 「…8:40の朝の音声で知らせ…『予測ではありません』と添える」
        with tempfile.TemporaryDirectory() as root:
            files, brain = setup(root)
            Path(brain, "研究結果", "シナリオ").mkdir(parents=True)
            line = Path(brain, "研究結果", "シナリオ", "最新.txt")
            line.write_text("2026-11-06 終値 9390／シナリオ：続く（底 9011 と外れの線 13218 の間）\n", encoding="utf-8")
            self.assertNotIn("注意です。SOXが", v.morning_text(files, brain, DAY))
            line.write_text("2026-11-06 終値 11200／シナリオ：続く（底 9011 と外れの線 13218 の間）／注意：戻りの天井（約11,383）の±3%に入った（終値 11,200）\n", encoding="utf-8")
            text = v.morning_text(files, brain, DAY)
            self.assertTrue(text.startswith("おはようございます。今日の注意です。注意です。SOXが、戻りの天井"))
            self.assertIn("予測ではありません。", text)
            line.write_text("2026-11-06 終値 8700／シナリオ：本番の下げ（底 9011 を割った）／注意：底の線 9,011 を割った（終値 8,700）／注意：−40%の線 8,781 を割った（終値 8,700）\n", encoding="utf-8")
            text = v.morning_text(files, brain, DAY)
            self.assertIn("注意です。SOXが、底の線 9,011 を割った、−40%の線 8,781 を割った。予測ではありません。", text)
            # an old line (more than 4 days before) is not said
            line.write_text("2026-10-30 終値 8700／注意：底の線 9,011 を割った（終値 8,700）\n", encoding="utf-8")
            self.assertNotIn("注意です。SOXが", v.morning_text(files, brain, DAY))

    def test_the_script_has_no_pc_path(self):
        src = (Path(__file__).resolve().parents[1] / "scripts" / "voice_notice.py").read_text(encoding="utf-8")
        for word in ("C:\\\\", "C:/", "Users"):
            self.assertNotIn(word, src)
        self.assertNotIn("order", src.lower().replace("ordered", ""))


if __name__ == "__main__":
    unittest.main()
