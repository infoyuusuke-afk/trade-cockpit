"""OWNER 2026-11-18 「上部に今日の予測シナリオかいて」 and 「メル今日は無効にして、日付の直しを次の版に」."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v10_positions_live as pos  # noqa: E402

HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
JST = timezone(timedelta(hours=9))


def write_mel(rt, day, doc, at="15:10"):
    d = Path(rt) / pos.MEL_DIR
    d.mkdir(parents=True, exist_ok=True)
    f = d / ("overnight_size_%s.json" % day)
    f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    t = datetime.strptime(day + " " + at, "%Y-%m-%d %H:%M").replace(tzinfo=JST).timestamp()
    os.utime(f, (t, t))


class MelDateCheck(unittest.TestCase):
    def base(self, day, **kw):
        doc = {"schema_version": "100b-v10-mel-overnight-size-v1", "day": day, "decided_at": day + " 15:10:00",
               "decisions": [{"code": "9506", "size": "半分", "reason": "x"}], "real_submit_allowed": False, "trade_instruction": False}
        doc.update(kw)
        return doc

    def test_from_1119_the_candidates_must_match(self):
        with tempfile.TemporaryDirectory() as rt:
            write_mel(rt, "2026-11-19", self.base("2026-11-19", candidates=["9506", "8001"]))
            self.assertEqual(pos.mel_plan(Path(rt), "2026-11-19")["9506"]["size"], "半分")
        with tempfile.TemporaryDirectory() as rt:     # the 11/18 accident: a decision for a stock that is not a candidate of the day
            write_mel(rt, "2026-11-19", self.base("2026-11-19", candidates=["8001", "5401"]))
            self.assertEqual(pos.mel_plan(Path(rt), "2026-11-19"), {})
        with tempfile.TemporaryDirectory() as rt:     # no candidates written -> not used
            write_mel(rt, "2026-11-19", self.base("2026-11-19"))
            self.assertEqual(pos.mel_plan(Path(rt), "2026-11-19"), {})

    def test_days_before_keep_the_old_rule(self):
        with tempfile.TemporaryDirectory() as rt:
            write_mel(rt, "2026-11-17", self.base("2026-11-17"))
            self.assertEqual(pos.mel_plan(Path(rt), "2026-11-17")["9506"]["size"], "半分")
        self.assertEqual(pos.MEL_CANDIDATES_FROM, "2026-11-19")


class Gateway(unittest.TestCase):
    def test_route_and_checks(self):
        self.assertIn("if ($path -eq '/today_scenario.json') {", GW)
        i = GW.index("function Get-TodayScenarioView")
        f = GW[i:GW.index("\n}\n", i) if "\n}\n" in GW[i:] else i + 2500]
        for w in ("'today_scenario_v1.json'", "-gt 65536", "ReparsePoint", "'100b-v10-today-scenario-v1'",
                  "$view.real_submit_allowed -ne $false", "$view.trade_instruction -ne $false"):
            self.assertIn(w, f)
        start = GW.index("# OWNER 2026-11-18 \"write today's forecast scenario at the top\"")
        GW[start:start + 2500].encode("ascii")    # Gateway additions are ASCII only


class Screen(unittest.TestCase):
    def setUp(self):
        i = HTML.index("OWNER 2026-11-18 「上部に今日の予測シナリオかいて」: /today_scenario.json")
        self.b = HTML[i:HTML.index("</script>", i)]

    def test_box_under_the_band(self):
        # OWNER 2026-11-18 「今やることに追記」: inside the 今やること box, under its heading
        self.assertIn('const host=document.getElementById("tl-now");if(!host){setTimeout(paint,3000);return;}', self.b)
        self.assertIn('if(h2.nextElementSibling!==box)h2.after(box);', self.b)
        self.assertIn("j.real_submit_allowed!==false||j.trade_instruction!==false", self.b)
        self.assertIn('String(x.made_day||"")===today', self.b)
        self.assertIn("次の営業日（", self.b)
        self.assertIn("研究のみ・売買の合図ではありません", self.b)
        self.assertIn("esc(l)", self.b)
        for w in ("cockpitSpeak", "RssOrder", "/control", "speechSynthesis"):
            self.assertNotIn(w, self.b)

    def test_scenarios_shown_as_written(self):
        # OWNER 2026-11-18 「しっかりシナリオ予測して」: the 【シナリオ】 lines (本線・別線), escaped, at most 3
        self.assertIn("Array.isArray(main.scenarios)&&main.scenarios.length", self.b)
        self.assertIn("main.scenarios.slice(0,3).map(l=>'<li>'+esc(l)+'</li>')", self.b)
        self.assertIn("(Array.isArray(main.lines)?main.lines:[])", self.b)        # audit 5732330: a wrong shape does not stop the paint
        self.assertIn('if(!host){setTimeout(paint,3000);return;}', self.b)

    def test_total_words_escaped(self):
        self.assertIn('return Object.keys(m).map(k=>"・"+esc(k)+" "+m[k]).join("");};', HTML)


if __name__ == "__main__":
    unittest.main()
