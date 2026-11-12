"""OWNER 2026-11-12 「決算またいだ銘柄がわからない」."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
sys.path.insert(0, str(ROOT / "scripts"))
import v10_positions_live as m  # noqa: E402


class EarningsHoldNames(unittest.TestCase):
    def test_split_lists_the_earnings_holds(self):
        with tempfile.TemporaryDirectory() as d:
            rt = Path(d)
            day = rt / "records" / "2026-11-11"
            day.mkdir(parents=True)
            (day / m.EARN_MARK_FILE).write_text(json.dumps({"date": "2026-11-11", "marks": {
                "4004": {"label": "今夜決算", "date": "2026-11-11", "time": ""}, "5016": None}}), encoding="utf-8")
            with open(rt / m.HISTORY_FILE, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["decision_date", "ticker", "name", "side", "return_close_pct", "status"])
                w.writeheader()
                w.writerow({"decision_date": "2026-11-11", "ticker": "4004.T", "name": "テスト化学（4004）", "side": "LONG", "return_close_pct": "12.76", "status": "検証済み"})
                w.writerow({"decision_date": "2026-11-11", "ticker": "5016.T", "name": "テスト金属（5016）", "side": "LONG", "return_close_pct": "-3.7", "status": "検証済み"})
            out = m.earnings_split(rt)
        self.assertEqual(out["earnings"]["n"], 1)
        self.assertEqual(out["other"]["n"], 1)
        self.assertEqual(out["earnings_items"], [{"day": "2026-11-11", "code": "4004", "name": "テスト化学（4004）", "side": "LONG", "pct": 12.76, "label": "今夜決算"}])

    def test_page_names_them_and_labels_the_stopped_cards(self):
        self.assertIn("const its=Array.isArray(t.earnings_items)?t.earnings_items:[];", HTML)
        self.assertIn("決算またぎの銘柄：", HTML)
        self.assertIn("%は15:25の日の引け→翌日14:00", HTML)
        i = HTML.index("const drawHolds=on=>{")
        block = HTML[i:HTML.index("drawHolds(window.__overnightHolds);", i)]
        self.assertIn("const es=window.cockpitEarningsSoon,em=es&&es.items?es.items[", block)
        self.assertIn("📅 決算またぎ", block)
        self.assertIn('(em?" earn-card":"")', block)


if __name__ == "__main__":
    unittest.main()
