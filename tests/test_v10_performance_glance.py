"""OWNER 2026-10-27 「AIコクピットの成績が一目で分かるように改修…全体成績、保有銘柄の損益（含み損・益）
各投資手法別 各アナリスト別 コントロールタブで…数字、グラフも良いかも」: a 成績（ひと目で） panel at the top of
CONTROL, and analyst_scores.json (GPT answers scored by direction at the close) served from the public feed."""
import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v10_public_feed_sync as feed  # noqa: E402

LOG_FIELDS = ["seen_at", "source", "role", "note", "posted_at", "code", "name", "strength", "view", "reason", "sources",
              "in_universe"]
OUT_FIELDS = LOG_FIELDS + ["price_at_seen", "price_30m", "price_60m", "price_close", "hit_30m", "hit_60m", "hit_close"]


class AnalystView(unittest.TestCase):
    def test_scores_only_bull_and_bear_rows_by_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "2026-01-05"
            day.mkdir()
            rows = [dict(source="gpt", role="pre_next", view="強気", price_at_seen="100", price_close="103"),
                    dict(source="gpt", role="pre_next", view="弱気", price_at_seen="100", price_close="101"),
                    dict(source="gpt", role="pre_next", view="監視", price_at_seen="100", price_close="90"),
                    dict(source="grok", role="", view="強気", price_at_seen="100", price_close="120")]
            for name, fields in (("manual_notes.csv", LOG_FIELDS), ("manual_notes_outcomes.csv", OUT_FIELDS)):
                with open(day / name, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(rows)
            v = feed.analyst_view(Path(tmp), datetime(2026, 1, 5, tzinfo=timezone.utc))
        self.assertEqual(len(v["analysts"]), 1)
        a = v["analysts"][0]
        self.assertEqual((a["name"], a["answers"], a["watch"], a["scored"], a["hits"]), ("PRE-NEXT", 3, 1, 2, 1))
        self.assertEqual(a["hit_rate_pct"], 50.0)
        self.assertAlmostEqual(a["avg_move_pct"], 1.0)          # (+3 and -1) / 2
        self.assertFalse(v["real_submit_allowed"])

    def test_sync_writes_the_file_and_the_gateway_serves_it(self):
        src = (ROOT / "scripts" / "v10_public_feed_sync.py").read_text(encoding="utf-8")
        self.assertIn('ANALYST_FILE = "analyst_scores.json"', src)
        self.assertIn("files[ANALYST_FILE] = {\"ok\": True", src)
        gw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertEqual(gw.count("'analyst_scores.json', 'market_summary.json', 'public_feed_meta.json'"), 2)


class GlancePanel(unittest.TestCase):
    def test_panel_sits_at_the_top_of_control_with_the_four_parts(self):
        js = (ROOT / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn('id="owner-performance-glance"', js)
        self.assertIn("if(intro)intro.after(section);else control.prepend(section);", js)
        for title in ("実口座 今日の確定損益（概算）", "実口座 含み損益", "コクピット仮想 今日の決済", "コクピット仮想 含み損益（平均）",
                      "保有銘柄の損益（含み）", "手法別（ブレインの仮想売買", "アナリスト別（答えの向きの当たり・費用なし）"):
            self.assertIn(title, js)
        self.assertIn("setInterval(renderGlance,10000);", js)
        self.assertIn("0件とは扱いません", js)

    def test_short_open_pl_matches_the_scoring(self):
        js = (ROOT / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn("(short?1-u.now/e:u.now/e-1)*100", js)


class RealTodaySplit(unittest.TestCase):
    """OWNER 2026-10-27 「買い→売埋と空売り→買埋を分けて計算して、前日以前の建玉の決済は『未計算○件』と出して」"""

    def test_long_and_short_are_matched_separately_and_earlier_positions_are_not_guessed(self):
        js = (ROOT / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn('/^(買建|買付)$/.test(s)?["long","open"]:/^(売埋|売付)$/.test(s)?["long","close"]:/^売建$/.test(s)?["short","open"]:/^買埋$/.test(s)?["short","close"]', js)
        self.assertIn("if(!o||c.q>o.q)realUncalc++;", js)
        self.assertIn("const q=Math.min(o.q,c.q),est=(c.p-o.p)*q*(g.dir===\"short\"?-1:1);", js)
        self.assertIn("未計算\"+realUncalc+\"件（前日以前の建玉の決済）", js)


if __name__ == "__main__":
    unittest.main()


def test_bars_line_up_with_fixed_value_columns():
    # OWNER 2026-10-27 「横グラフの位置を統一」: the value column has a fixed width, so every bar starts at the same place.
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert ".g-row.g-row5{grid-template-columns:70px minmax(160px,1fr) 120px 190px}.g-row.g-row5>b{text-align:right}" in html
    assert "minmax(150px,1.6fr) minmax(120px,1.4fr) 120px 190px 90px;" in html
    assert "minmax(110px,auto)" not in html and "minmax(120px,auto)}" not in html


import unittest as _unittest  # noqa: E402


class FunctionTests(_unittest.TestCase):
    """The test_ functions above, run by `python -m unittest` (CI) as well."""


for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and callable(_fn):
        setattr(FunctionTests, _name, (lambda f: lambda self: f())(_fn))


class VirtualTodayYen(unittest.TestCase):
    def test_virtual_today_tile_also_in_yen_at_100_shares(self):
        # OWNER 2026-10-27 「金額もいれる」
        js = (ROOT / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn("vYen=vYenRows.reduce((a,p)=>a+Number(p.return_pct)/100*Number(p.fill_price)*100,0);", js)
        self.assertIn('closed.length?gPct(vSum)+"／"+gYen(vYen):"まだなし"', js)

