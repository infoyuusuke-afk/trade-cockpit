"""OWNER 2026-11-16 「オーバーナイト銘柄に、翌朝の注意予定（海外大型決算・米指標・休場前）の印と予定名を出して、半導体銘柄はエヌビディア決算の夜に
特に印を付けて。株数は通常と半分の両方を仮想で記録して比べる…表示と仮想の記録だけで、注文はしない」."""
import json
import sys
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
        nv = dict(HOLD, ticker="8035.T", risk=[{"what": "NVIDIAの決算"}])
        self.assertEqual(pos.size([dict(nv)], 3_000_000, "10:00", ai_size=True)["_taken"][0]["shares"], 2500)
        self.assertEqual(pos.size([dict(nv)], 3_000_000, "10:00")["_taken"][0]["shares"], 3000)   # normal unchanged
        src = (ROOT / "scripts" / "v10_positions_live.py").read_text(encoding="utf-8")
        self.assertIn("a = size(trades, capital, now_hm, ev, ai_size=True)", src)
        self.assertIn('keep["sizes"][label]["ai_done"] = s["risk_ai"]["done"]', src)
        self.assertIn('row("　AIの判断（予定の夜の値動きの幅に合わせて減らす）",', HTML)
        self.assertIn('row("　半分（予定のある夜は半分）",', HTML)

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
