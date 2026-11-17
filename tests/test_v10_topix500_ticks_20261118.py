"""OWNER 2026-11-17 「費用の刻みを直す版を作って：TOPIX500の銘柄はJPX公式の一覧で確かめて細かい刻み、それ以外は粗い刻み。一覧の日付も記録する」."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v10_signal_ev_table as ev  # noqa: E402
import v10_trial_methods as tm  # noqa: E402

DOC = json.loads((ROOT / "config" / "topix500_ticks_v1.json").read_text(encoding="utf-8"))


class Topix500Ticks(unittest.TestCase):
    def test_list_records_its_source_and_date(self):
        self.assertEqual(DOC["schema_version"], "100b-v10-topix500-ticks-v1")
        self.assertEqual(DOC["list_date"], "2026-09-30")
        self.assertIn("jpx.co.jp", DOC["list_source"])
        self.assertIn("jpx.co.jp/equities/trading/domestic/07.html", DOC["tick_rule_source"])
        self.assertEqual(DOC["changes_applied"]["date"], "2026-10-30")
        self.assertIn("5805", DOC["codes"])
        self.assertNotIn("4587", DOC["codes"])
        self.assertGreater(len(DOC["codes"]), 450)

    def test_fine_table_for_listed_codes_coarse_otherwise(self):
        # the JPX table: TOPIX500 / other
        for price, fine, coarse in ((900, 0.1, 1), (2500, 0.5, 1), (4000, 1, 5), (9000, 1, 10), (20000, 5, 10),
                                    (40000, 10, 50), (73250, 10, 100), (200000, 50, 100), (400000, 100, 500)):
            self.assertEqual(ev.tick_size(price, "6861.T"), fine, price)
            self.assertEqual(ev.tick_size(price, "9999.T"), coarse, price)
            self.assertEqual(ev.tick_size(price), coarse, price)          # no code: never lighter than before
            self.assertEqual(tm._tick(price, "6861"), fine, price)

    def test_strict_cost_uses_the_code(self):
        self.assertLess(ev.strict_cost_pct(1, 73250, 73070, "6861.T"), ev.strict_cost_pct(1, 73250, 73070))
        r = ev.replay({"signal": "買いサイン", "entry": "100", "stop": "99", "target1": "102", "captured_at": "2026-11-17 10:00:00",
                       "ticker": "6861.T"}, [("10:00:10", 0, 100.0), ("10:00:20", 0, 102.0)])
        if r and r.get("state") == "FILLED":
            self.assertAlmostEqual(r["return_pct"], r["gross_pct"] - ev.strict_cost_pct(1, r["fill_price"], r["exit_price"], "6861.T"), places=9)


class Topix500ListGuard(unittest.TestCase):
    """audit 22a943e: the list is pinned by SHA-256 and is not used after valid_until (both fall back to the coarse table)."""

    def test_pin_matches_the_file_in_both_modules(self):
        import hashlib
        h = hashlib.sha256((ROOT / "config" / "topix500_ticks_v1.json").read_bytes()).hexdigest()
        self.assertEqual(ev.TOPIX500_SHA256, h)
        self.assertEqual(tm._TOPIX500_SHA256, h)
        self.assertEqual(DOC["valid_until"], "2027-02-26")

    def test_edited_list_falls_back_to_coarse(self):
        import tempfile
        from unittest import mock
        doc = dict(DOC, codes=list(DOC["codes"]) + ["9999"])
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "topix500_ticks_v1.json"
            f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(ev, "TOPIX500_FILE", f):
                self.assertEqual(ev._topix500(), frozenset())
        with mock.patch.object(ev, "TOPIX500_FILE", ROOT / "config" / "no_such_file.json"):
            self.assertEqual(ev._topix500(), frozenset())

    def test_expired_list_falls_back_to_coarse(self):
        from datetime import datetime as real
        from unittest import mock

        class Later(real):
            @classmethod
            def now(cls, tz=None):
                return real(2027, 3, 1, 9, 0, tzinfo=tz)

        class LastDay(real):
            @classmethod
            def now(cls, tz=None):
                return real(2027, 2, 26, 15, 0, tzinfo=tz)

        for mod in (ev, tm):
            with mock.patch.object(mod, "datetime", Later):
                self.assertEqual(mod._topix500(), frozenset(), mod.__name__)
            with mock.patch.object(mod, "datetime", LastDay):
                self.assertIn("6861", mod._topix500(), mod.__name__)


if __name__ == "__main__":
    unittest.main()
