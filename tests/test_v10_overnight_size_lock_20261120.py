"""OWNER 2026-11-20 「15:25に決めた株数をその場で記録に固めて、次の日はそれを使う版を作って」. Synthetic data only; virtual, no orders."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v10_positions_live as live  # noqa: E402


def hold(ticker, side, rule, fill, decided="2026-11-20"):
    return {"kind": "overnight", "rule": rule, "ticker": ticker, "name": ticker, "side": side, "fill": fill, "in": "09:00", "out": "14:00",
            "last": None, "ticks": [], "decided": decided, "risk": [], "mel": None}


class SizeLock(unittest.TestCase):
    def test_locked_shares_win_over_a_flipped_figure(self):
        tr = [hold("A", 1, "ON_LONG", 1000.0)]
        free = live.size(tr, 1_000_000, "09:00", {"ON_LONG": -0.2})
        self.assertEqual([(x["ticker"], x["shares"]) for x in free["_taken"]], [("A", 1000)])   # figured now: 1,000 shares
        locked = {"A": {"shares": 300, "risk_cut": False}}
        got = live.size(tr, 1_000_000, "09:00", {"ON_LONG": -0.2}, locked=locked)
        self.assertEqual([(t["ticker"], t["shares"]) for t in got["_taken"]], [("A", 300)])

    def test_locked_zero_keeps_its_reason(self):
        tr = [hold("B", -1, "ON_SHORT", 2000.0)]
        locked = {"B": {"shares": 0, "skip": {"reason": "成績がマイナスの手法なので、最後の1回分の枠を残した", "need": 2_000_000, "room": 1_500_000}}}
        got = live.size(tr, 3_000_000, "09:00", {"ON_SHORT": 0.5}, locked=locked)
        self.assertEqual(got["_taken"], [])
        z = live.zero_reason(got["_skipped_overnight"][0])
        self.assertEqual(z["words"], "枠が足りず0株")
        self.assertTrue(z["reserve"])
        self.assertEqual(z["need"], 2_000_000)

    def test_lock_is_per_deciding_day_size_and_way(self):
        with tempfile.TemporaryDirectory() as d:
            rec = Path(d)
            (rec / "2026-11-20").mkdir()
            (rec / "2026-11-20" / live.SIZE_LOCK_FILE).write_text(json.dumps(
                {"date": "2026-11-20", "sizes": {"300万": {"通常": {"A": {"shares": 600}}, "半分": {"A": {"shares": 300}}}}}), encoding="utf-8")
            tr = [hold("A", 1, "ON_LONG", 1000.0), hold("C", 1, "ON_LONG", 1000.0, decided="2026-11-19")]
            locks = live.size_locks(rec, tr)
            self.assertEqual(list(locks), ["2026-11-20"])
            self.assertEqual(live.locked_for(locks, tr, "300万", "通常"), {"A": {"shares": 600}})
            self.assertEqual(live.locked_for(locks, tr, "300万", "半分"), {"A": {"shares": 300}})
            self.assertIsNone(live.locked_for(locks, tr, "300万", "AI"))      # no lock for that way: figured as before

    def test_existing_lock_is_never_rewritten(self):
        with tempfile.TemporaryDirectory() as d:
            day = Path(d) / "2026-11-20"
            day.mkdir()
            f = day / live.SIZE_LOCK_FILE
            f.write_text(json.dumps({"date": "2026-11-20", "locked_at": "15:25", "sizes": {}}), encoding="utf-8")
            got = live.lock_overnight_sizes(Path(d), day, "2026-11-20", "2026-11-24", {"ev": {"ON_LONG": 1.0}}, "16:00")
            self.assertEqual(got["locked_at"], "15:25")
            self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["locked_at"], "15:25")

    def test_written_with_exclusive_create_after_1525(self):
        text = (ROOT / "scripts" / "v10_positions_live.py").read_text(encoding="utf-8-sig")
        self.assertIn('with open(f, "x", encoding="utf-8") as fh:', text)
        self.assertIn("lock_overnight_sizes(runtime, day_dir, today, _next_weekday(local.date()).isoformat(), capital.get(\"rule_ev\"), hm)", text)
        a = text.index("def lock_overnight_sizes(")
        b = text.index("def size_locks(", a)
        for w in ("RssStockOrder", "RssMarginOpenOrder", "real_submit_allowed\": True"):
            self.assertNotIn(w, text[a:b])


if __name__ == "__main__":
    unittest.main()
