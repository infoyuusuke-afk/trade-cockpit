"""OWNER 2026-11-18 「1つの版で直して：①OVERNIGHT 5で15:25に持ち越しが決まった時に、5銘柄それぞれ通常・半分・AIの株数と、枠が足りない銘柄は
『枠が足りず0株（要る金額・残りの枠）』をその場で出す。次の日の結果でも『見送り』ではなく同じ言葉にする。合計の数も直す ②テーマタブの値段の横に
『きのうの終値』と大きく出す。表示だけ、声なし、注文しない」."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v10_positions_live as pos  # noqa: E402

HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def hold(code, price, side="SHORT"):
    return {"decided_at": "2026-11-18 15:25:00", "name": "N（%s）" % code, "reference_price": str(price), "side": side,
            "ticker": code + ".T", "valid_until": ""}


class ZeroReason(unittest.TestCase):
    def test_words_from_the_sizing(self):
        self.assertEqual(pos.zero_reason({"reason": "枠が足りない", "need": 2901600, "room": 952700}),
                         {"words": "枠が足りず0株", "need": 2901600, "room": 952700, "reserve": False})
        self.assertTrue(pos.zero_reason({"reason": "成績がマイナスの手法なので、最後の1回分の枠を残した", "need": 1, "room": 9})["reserve"])
        self.assertEqual(pos.zero_reason({"reason": "メルの判断で0（入らない）"})["words"], "メルの判断で0株")
        self.assertEqual(pos.zero_reason({"reason": "1単元（100株）が資金より高い", "need": 4_000_000})["words"], "1単元が資金より高く0株")
        self.assertIsNone(pos.zero_reason(None))

    def test_size_keeps_every_overnight_skip(self):
        trades = [{"kind": "overnight", "rule": "ON_SHORT", "ticker": c + ".T", "name": c, "side": -1, "fill": float(p), "in": "09:00",
                   "out": None, "ret": None, "exit": None, "last": None, "ticks": []}
                  for c, p in (("9506", 1290), ("4493", 1760), ("593A", 1990), ("4475", 2232), ("8058", 5172))]
        got = pos.size(trades, 3_000_000, "09:00")
        self.assertEqual([t["ticker"] for t in got["_taken"]], ["9506.T", "4493.T", "593A.T"])
        sk = {x["ticker"]: x for x in got["_skipped_overnight"]}
        self.assertEqual(set(sk), {"4475.T", "8058.T"})
        self.assertEqual(sk["4475.T"]["need"], 2232 * 1300)
        self.assertEqual(sk["4475.T"]["room"], round(3_000_000 * pos.MARGIN_MULT - (1290 * 2300 + 1760 * 1700 + 1990 * 1500)))
        self.assertEqual(pos.zero_reason(sk["8058.T"])["words"], "枠が足りず0株")


class Tonight(unittest.TestCase):
    def test_tonight_sizing_right_after_1525(self):
        with tempfile.TemporaryDirectory() as d:
            rt = Path(d)
            day = rt / "records" / "2026-11-18"
            day.mkdir(parents=True)
            picks = [hold("9506", 1290), hold("4493", 1760), hold("593A", 1990), hold("4475", 2232), hold("8058", 5172)]
            orig = pos._overnight
            pos._overnight = lambda day_dir, valid_until: [dict(x) for x in picks]
            try:
                got = pos.overnight_tonight(rt, day, "2026-11-18", "2026-11-19", {"ev": {"ON_SHORT": 0.4}})
            finally:
                pos._overnight = orig
        self.assertEqual(got["state"], "OK")
        self.assertEqual(got["limit"], round(3_000_000 * pos.MARGIN_MULT))
        rows = {r["ticker"]: r for r in got["rows"]}
        self.assertEqual(len(rows), 5)
        for k in ("通常", "半分", "AI"):
            self.assertEqual(rows["9506.T"][k]["shares"], 2300)
            self.assertEqual(rows["4475.T"][k]["shares"], 0)
            self.assertEqual(rows["4475.T"][k]["zero"]["words"], "枠が足りず0株")
            self.assertEqual(rows["4475.T"][k]["zero"]["need"], 2232 * 1300)
            self.assertEqual(rows["8058.T"][k]["zero"]["words"], "枠が足りず0株")
        self.assertFalse(got["real_submit_allowed"])

    def test_build_adds_it_only_after_1525(self):
        src = (ROOT / "scripts" / "v10_positions_live.py").read_text(encoding="utf-8")
        i = src.index('capital["overnight_tonight"] = overnight_tonight(')
        self.assertIn("hm >= DECIDE_AT and not weekend and (day_dir / OVERNIGHT_FILE).is_file()", src[i - 400:i])
        self.assertIn('{"state": "UNAVAILABLE", "reason": type(exc).__name__, "rows": []}', src[i:i + 500])


class Screen(unittest.TestCase):
    def setUp(self):
        i = HTML.index("「保有と持ち越しを一目で見る版」 (OVERNIGHT 5)")
        self.b = HTML[i:HTML.index("</script>", i)]

    def test_tonight_table_and_words(self):
        self.assertIn("pos.capital.overnight_tonight.state===\"OK\"", self.b)
        self.assertIn("メル 300万の今夜の株数（15:25に決まった分", self.b)
        self.assertIn('z.words+(z.need!==null&&z.need!==undefined?"（要る "+man(z.need)', self.b)
        self.assertIn('"・残りの枠 "+man(z.room)', self.b)
        self.assertIn('skipLabel:sh<=0?(ai.zero?ai.zero.words:"0株"):""', self.b)
        for word in ("cockpitSpeak", "RssOrder", "/control", "speechSynthesis"):
            self.assertNotIn(word, self.b)

    def test_total_counts_each_word(self):
        self.assertIn('const k=r.skipLabel||"見送り";m[k]=(m[k]||0)+1;', HTML)
        self.assertIn("'・待ち '+n(\"wait\")+skipCount(list)+'</td>", HTML)
        self.assertNotIn("(n(\"skip\")?'・見送り '+n(\"skip\"):'')", HTML)


class ThemeClose(unittest.TestCase):
    def test_label_beside_the_price(self):
        i = HTML.index("「テーマタブの値段の横に『きのうの終値』と大きく出す」")
        b = HTML[i:i + 2500]
        self.assertIn('return day===d.toISOString().slice(0,10)?"きのうの終値":', b)
        self.assertIn('if(day===today)return "今日の終値";', b)
        self.assertIn("window.cockpitHolidays", b)
        self.assertIn('<span class="tw-ago">\'+esc(closeLabel(String(c.day||"")))+\'</span>', b)
        self.assertIn(".tw-card .tw-ago{display:block;", HTML)
        self.assertIn("font-size:14px;font-weight:800", HTML[HTML.index(".tw-card .tw-ago{"):HTML.index(".tw-card .tw-ago{") + 300])


if __name__ == "__main__":
    unittest.main()
