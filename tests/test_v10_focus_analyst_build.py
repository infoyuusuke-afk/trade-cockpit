"""OWNER 2026-11-09 「FOCUSのアナリスト銘柄を書き出すPCの仕組みと16:00の記録をGitHubに上げて監査に回して」. Synthetic data only."""
import unittest
from pathlib import Path

from scripts import v10_focus_analyst_build as fa
from scripts import v10_positions_live as pos

PLAN_A = """前置きの文（使わない）
ANALYST_PLAN_V1
1111|A社|買い|中|寄り|−1%|14:30|メモ
2222|B社|売り|高|9:05|+1%|11:00|
9999|Z社|買い|高|寄り|−1%|引け|
END
1111|あとの行は読まない|買い|高|寄り|x|x|
"""
PLAN_B = """ANALYST_PLAN_V1
1111|A社|買い|高|押し目|−2%|引け|
333A|C社|買い|低|寄り|−1%|引け|
END
"""
UNI = {"1111": "A社", "2222": "B社", "333A": "C社"}


class Pick(unittest.TestCase):
    def test_confidence_order_best_confidence_and_universe(self):
        items = fa.pick([("1号", PLAN_A), ("2号", PLAN_B)], UNI)
        self.assertEqual([x["code"] for x in items], ["2222", "1111", "333A"])   # 9999 is not in the 100
        a = items[1]
        self.assertEqual((a["conf"], a["who"], a["ticker"]), ("高", "2号", "1111.T"))  # the best confidence wins
        self.assertEqual(a["entry"], "入る 押し目・損切り −2%・手じまい 引け")
        # the line after END is never read
        self.assertNotIn("あとの行は読まない", str(items))

    def test_at_most_eight(self):
        text = "ANALYST_PLAN_V1\n" + "\n".join("%04d|n|買い|中|寄り|x|x|" % (1000 + i) for i in range(12)) + "\nEND\n"
        uni = {"%04d" % (1000 + i): "n" for i in range(12)}
        self.assertEqual(len(fa.pick([("1号", text)], uni)), 8)

    def test_text_without_a_plan_is_skipped(self):
        self.assertEqual(fa.pick([("1号", "ふつうの文"), ("2号", None)], UNI), [])


class Slots(unittest.TestCase):
    def test_each_slot_once_and_never_rewritten(self):
        calls = []
        make = lambda: calls.append(1) or [{"ticker": "1111.T"}]
        doc, ch = fa.build_slots(None, "08:40", "2026-11-10", make)
        self.assertEqual((doc["slots"], ch), ({}, False))
        doc, ch = fa.build_slots(doc, "08:55", "2026-11-10", make)
        self.assertEqual((list(doc["slots"]), doc["slots"]["0850"]["made_at"], ch), (["0850"], "08:55", True))
        doc, ch = fa.build_slots(doc, "09:30", "2026-11-10", make)
        self.assertFalse(ch)
        doc, ch = fa.build_slots(doc, "12:25", "2026-11-10", make)
        self.assertEqual((sorted(doc["slots"]), len(calls)), (["0850", "1220"], 2))
        self.assertIs(doc["real_submit_allowed"], False)
        self.assertIs(doc["trade_instruction"], False)
        # the next day starts again
        doc2, _ = fa.build_slots(doc, "08:50", "2026-11-11", make)
        self.assertEqual((doc2["date"], list(doc2["slots"])), ("2026-11-11", ["0850"]))

    def test_the_file_is_what_the_cockpit_reads(self):
        import json
        import tempfile
        from pathlib import Path
        doc, _ = fa.build_slots(None, "08:50", "2026-11-10", lambda: fa.pick([("1号", PLAN_A)], UNI))
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / pos.FOCUS_ANALYST_FILE).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            v = pos.focus_analyst(Path(d), "2026-11-10", "09:00")
        self.assertEqual((v["state"], [x["code"] for x in v["items"]]), ("OK", ["2222", "1111"]))


class Record(unittest.TestCase):
    def doc(self, made_at="08:50"):
        return {"date": "2026-11-10", "slots": {"0850": {"made_at": made_at, "items": [
            {"ticker": "1111.T", "code": "1111", "name": "A社", "side": "買い", "conf": "高", "who": "1号"},
            {"ticker": "2222.T", "code": "2222", "name": "B社", "side": "売り", "conf": "高", "who": "1号"}]}}}

    TICKS = [{"ticker": "1111.T", "price": "1,000", "exchange_time": "09:00:00"},
             {"ticker": "1111.T", "price": "1100", "exchange_time": "10:00:00"},
             {"ticker": "1111.T", "price": "1050", "exchange_time": "15:30:00"},
             {"ticker": "1111.T", "price": "5000", "exchange_time": "15:31:00"},   # after the session: not used
             {"ticker": "2222.T", "price": "500", "exchange_time": "09:01:00"},
             {"ticker": "2222.T", "price": "450", "exchange_time": "15:00:00"},
             {"ticker": "3333.T", "price": "1", "exchange_time": "09:00:00"}]

    def test_moves_in_the_direction(self):
        rows, lines = fa.record(self.doc(), self.TICKS, "2026-11-10")
        self.assertEqual(rows[0][7:12], [1000.0, 1100.0, 1000.0, 1050.0, 5.0])
        self.assertEqual(rows[1][11], 10.0)                        # a short gains when the price falls
        self.assertIn("売買の勧めではありません", lines[-1])

    def test_no_look_ahead_when_the_slot_was_made_late(self):
        rows, _ = fa.record(self.doc(made_at="09:30"), self.TICKS, "2026-11-10")
        self.assertEqual(rows[0][7], 1100.0)                       # not the 09:00 price
        self.assertEqual(rows[1][7], 450.0)                        # 2222: the 09:01 tick is before 09:30, the 15:00 one is used
        rows2, lines2 = fa.record(self.doc(made_at="15:10"), self.TICKS, "2026-11-10")
        self.assertTrue(any("その後の値段の記録なし" in x for x in lines2))

    def test_other_day_and_broken_files(self):
        self.assertEqual(fa.record(self.doc(), self.TICKS, "2026-11-11")[0], [])
        self.assertEqual(fa.record([1], self.TICKS, "2026-11-10")[0], [])
        self.assertEqual(fa.record({"date": "2026-11-10", "slots": {"0850": {"items": ["x"]}}}, self.TICKS, "2026-11-10")[0], [])

    def test_merge_replaces_only_that_day(self):
        old = [["2026-11-09", "0850", "1"], ["2026-11-10", "0850", "old"]]
        self.assertEqual(fa.merge_csv(old, [["2026-11-10", "0850", "new"]], "2026-11-10"),
                         [["2026-11-09", "0850", "1"], ["2026-11-10", "0850", "new"]])

    def test_no_order_words_in_the_module(self):
        from pathlib import Path
        src = Path(fa.__file__).read_text(encoding="utf-8")
        for w in ("submit_order", "place_order", "requests.", "urllib", "subprocess", "C:\\\\", "Desktop"):
            self.assertNotIn(w, src)


if __name__ == "__main__":
    unittest.main()


class FocusAnalystSide(unittest.TestCase):
    def test_side_chip_on_every_analyst_card(self):
        # OWNER 2026-11-11 「アナリスト銘柄はLONG方向か、一目でわかるように」: a coloured chip above the card, also while the card is closed
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        self.assertIn('(buy?"▲ LONG（買い）":"▼ SHORT（空売り）")', html)
        self.assertIn("#focus-analyst .fa-side.long{", html)
        self.assertIn("'<div class=\"focus-pin fa-'+(dir||\"none\")+'\">", html)
