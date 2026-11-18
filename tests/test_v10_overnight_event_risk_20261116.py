"""OWNER 2026-11-16 「オーバーナイト銘柄に、翌朝の注意予定（海外大型決算・米指標・休場前）の印と予定名を出して、半導体銘柄はエヌビディア決算の夜に
特に印を付けて。株数は通常と半分の両方を仮想で記録して比べる…表示と仮想の記録だけで、注文はしない」."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v10_positions_live as pos  # noqa: E402

HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def _runtime(events):
    d = Path(tempfile.mkdtemp())
    (d / "public_feed").mkdir()
    (d / "public_feed" / "event_calendar.json").write_text(json.dumps({"events": events}, ensure_ascii=False), encoding="utf-8")
    return d


HOLD = {"kind": "overnight", "rule": "ON_LONG", "ticker": "X.T", "name": "X", "side": 1, "fill": 1000.0, "in": "09:00",
        "out": None, "ret": None, "exit": None, "last": 1010.0, "ticks": [], "days": 1, "decided": "2026-11-17"}


class OvernightEventMarks(unittest.TestCase):
    def test_events_inside_the_hold_window(self):
        rt = _runtime([
            {"date": "2026-12-09", "time_jst": "22:30", "impact": "高", "title": "米CPI"},        # the decision night: inside
            {"date": "2026-12-09", "time_jst": "10:00", "impact": "高", "title": "朝の指標"},     # before the decision: out
            {"date": "2026-12-10", "time_jst": "寄り付き", "impact": "高", "title": "SQ"},       # the exit morning: inside
            {"date": "2026-12-10", "time_jst": "22:30", "impact": "高", "title": "翌夜"},        # after the 14:00 exit: out
            {"date": "2026-12-10", "time_jst": "04:00", "impact": "中", "title": "米GDP"},       # impact 中: inside too
            {"date": "2026-12-10", "time_jst": "04:00", "impact": "低", "title": "低い予定"},    # impact 低: out
        ])
        got = {e["what"]: e for e in pos.hold_events(rt, "2026-12-09", "2026-12-10")}
        for w in ("米CPI", "SQ", "米GDP", "Broadcomの決算（米12/9引け後）"):
            self.assertIn(w, got)
        for w in ("朝の指標", "翌夜", "低い予定"):
            self.assertNotIn(w, got)
        self.assertEqual(got["米GDP"]["impact"], "中")
        v = pos.risk_view(rt, "2026-12-09", "2026-12-10")
        self.assertEqual(v["level"], "高")
        self.assertFalse(v["nvidia_night"])

    def test_holiday_before_counts(self):
        rt = _runtime([{"date": "2026-11-23", "time_jst": "終日", "impact": "中", "title": "日本株・先物とも休場"}])
        self.assertEqual([e["what"] for e in pos.hold_events(rt, "2026-11-20", "2026-11-24")], ["日本株・先物とも休場"])

    def test_nvidia_night_marks_the_semiconductors(self):
        rt = _runtime([])
        v = pos.risk_view(rt, "2026-11-17", "2026-11-18")
        self.assertEqual([e["what"] for e in v["events"]], ["NVIDIAの決算（米11/17引け後）"])
        self.assertTrue(v["nvidia_night"])
        for code in ("285A", "6857", "8035", "6920"):
            self.assertIn(code, v["semi_codes"])
        self.assertEqual(pos.hold_events(rt, "2026-11-16", "2026-11-17"), [])

    def test_normal_and_half_both_counted(self):
        risky = dict(HOLD, risk=[{"what": "NVIDIA"}])
        normal = pos.size([dict(risky)], 3_000_000, "10:00")["_taken"][0]
        half = pos.size([dict(risky)], 3_000_000, "10:00", half_on_risk=True)["_taken"][0]
        calm = pos.size([dict(HOLD)], 3_000_000, "10:00", half_on_risk=True)["_taken"][0]
        self.assertEqual((normal["shares"], half["shares"], calm["shares"]), (3000, 1500, 3000))
        self.assertTrue(half["risk_cut"])
        self.assertFalse(normal["risk_cut"])
        self.assertEqual(pos.size([dict(risky)], None, "10:00", half_on_risk=True)["_taken"][0]["shares"], 100)   # 100株 stays
        src = (ROOT / "scripts" / "v10_positions_live.py").read_text(encoding="utf-8")
        self.assertIn('h = size(trades, capital, now_hm, ev, half_on_risk=True)', src)
        self.assertIn('keep["sizes"][label]["half_done"] = s["risk_half"]["done"]', src)

    def test_ai_size_follows_the_measured_width(self):
        # OWNER 2026-11-16 「このリスクを踏まえてAIが判断してトレードして、おれはAIが判断した結果がみたい」
        self.assertEqual(pos.ai_ratio([{"what": "NVIDIAの決算（米11/17引け後）"}], "8035.T"), 1.2)
        self.assertEqual(pos.ai_ratio([{"what": "NVIDIAの決算（米11/17引け後）"}], "7203.T"), 1.0)
        self.assertEqual(pos.ai_ratio([{"what": "FOMC・SEP"}], "6857.T"), 2.2)
        self.assertEqual(pos.ai_ratio([{"what": "日本株・先物とも休場"}, {"what": "メジャーSQ"}], "9984.T"), 1.4)
        self.assertEqual(pos.ai_ratio([{"what": "米CPI（11月）"}], "8035.T"), 1.0)          # not measured: unchanged
        v = pos.risk_view(_runtime([]), "2026-11-17", "2026-11-18")
        self.assertIn(["NVIDIA", 1.2, 1.0], v["width_table"])      # what Mel reads as 過去の値動きの幅
        self.assertEqual(v["width_code"], {"FOMC|6857": 2.2})

    def test_mel_decision_locked_before_1525(self):
        # OWNER 2026-11-16 「毎日15:20にメルが…0・半分・通常から決めて理由を一言書く。15:25より前に固めて後から変えない」
        rt = _runtime([])
        (rt / "mel300").mkdir()
        f = rt / "mel300" / "overnight_size_2026-11-17.json"
        doc = {"schema_version": "100b-v10-mel-overnight-size-v1", "day": "2026-11-17", "decided_at": "2026-11-17 15:18:02",
               "decisions": [{"code": "8035", "size": "0", "reason": "NVIDIA決算の夜"}, {"code": "7203", "size": "半分", "reason": "幅"},
                             {"code": "6857", "size": "大きく", "reason": "形が違う"}]}
        f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        jst = timezone(timedelta(hours=9))
        at = lambda hm: datetime(2026, 11, 17, int(hm[:2]), int(hm[3:]), tzinfo=jst).timestamp()
        os.utime(f, (at("15:18"), at("15:18")))
        got = pos.mel_plan(rt, "2026-11-17")
        self.assertEqual(got["8035"]["size"], "0")
        self.assertEqual(got["7203"]["size"], "半分")
        self.assertNotIn("6857", got)                                # only 0・半分・通常
        os.utime(f, (at("15:30"), at("15:30")))
        self.assertEqual(pos.mel_plan(rt, "2026-11-17"), {})         # audit a8c6473: the file changed after 15:25: not used
        f.write_text(json.dumps(dict(doc, decided_at="2026-11-17 15:25:00"), ensure_ascii=False), encoding="utf-8")
        os.utime(f, (at("15:18"), at("15:18")))
        self.assertEqual(pos.mel_plan(rt, "2026-11-17"), {})         # at or after 15:25: not used
        a = dict(HOLD, ticker="8035.T", risk=[{"what": "NVIDIAの決算"}], mel={"size": "0", "reason": "x"})
        b = dict(HOLD, ticker="7203.T", mel={"size": "半分", "reason": "y"})
        c = dict(HOLD, ticker="9984.T", mel=None)
        taken = {t["ticker"]: t["shares"] for t in pos.size([dict(a), dict(b), dict(c)], 3_000_000, "10:00", mel=True)["_taken"]}
        self.assertEqual(taken, {"7203.T": 1500, "9984.T": 3000})     # 0 = not entered, 半分 = half, none = 通常
        normal = {t["ticker"]: t["shares"] for t in pos.size([dict(a), dict(b), dict(c)], 3_000_000, "10:00")["_taken"]}
        self.assertEqual(normal, {"8035.T": 3000, "7203.T": 3000, "9984.T": 3000})   # the normal sizing is unchanged
        src = (ROOT / "scripts" / "v10_positions_live.py").read_text(encoding="utf-8")
        self.assertIn("a = size(trades, capital, now_hm, ev, mel=True)", src)
        self.assertIn('s["overnight_compare"] = overnight_compare(trades, taken, h_taken, a_taken, now_hm,', src)
        self.assertIn('{"通常": n_skip, "半分": h_skip, "AI": a_skip})', src)   # OWNER 2026-11-18: with the reason of a 0-share way
        self.assertIn('"mel_tonight": mel_plan(runtime, today)', src)
        self.assertIn('row("　AIの判断（メルが15:20に0・半分・通常を決める）",', HTML)
        self.assertIn('row("　半分（予定のある夜は半分）",', HTML)

    def test_overnight_tab_shows_the_three_ways(self):
        i = HTML.index("「オーバーナイトの株数を、毎日15:20にメルが翌朝の注意予定と過去の値動きの幅を見て")
        b = HTML[i:HTML.index("</script>", i)]
        # OWNER 2026-11-17 「勝ったか、負けたか一目でわかる形」: a 結果 column first, the rest unchanged
        self.assertIn('["結果","銘柄","向き","翌朝の注意予定","メルの判断","通常","半分","AIの判断"]', b)
        self.assertIn('p.capital.sizes.find(s=>s.label==="300万")', b)
        self.assertIn("bp.real_submit_allowed===false", b)
        code = "\n".join(line for line in b.splitlines() if not line.lstrip().startswith("//"))
        self.assertNotIn("innerHTML", code)
        for banned in ("cockpitSpeak", "order", "RssOrder"):
            self.assertNotIn(banned, code)

    def test_screen_marks(self):
        self.assertIn("⚠ 持ち越しの間（次の営業日14:00まで）の注意予定：", HTML)
        self.assertIn("🔶 半導体・NVIDIA決算の夜：", HTML)
        self.assertIn("「通常」と「半分」の両方で数えて比べます。", HTML)
        self.assertIn("window.cockpitEventRisk=p.event_risk||null;", HTML)
        self.assertIn("window.cockpitEventTag=(x,e)=>{", HTML)
        self.assertEqual(HTML.count("(window.cockpitEventTag?window.cockpitEventTag(x,"), 2)   # both overnight cards
        i = HTML.index("window.cockpitEventTag=(x,e)=>{")
        block = HTML[i:HTML.index("};", i)]
        for banned in ("cockpitSpeak", "order", "RssOrder"):
            self.assertNotIn(banned, block)

    def test_same_us_results_as_the_screen(self):
        for d, _t, what in pos.OVERSEAS_EVENTS:
            self.assertIn('{date:"%s",' % d, HTML)
            self.assertIn(what.split("（")[0], HTML)


if __name__ == "__main__":
    unittest.main()
