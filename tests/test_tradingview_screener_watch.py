import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('tvs', Path(__file__).parents[1] / 'scripts/tradingview_screener_watch.py')
tvs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tvs)


def make_row(code, close, volume, change, rel_vol, atr, vwap, high, low, mcap, sector, exchange="TSE", name="Sample Co"):
    return {"s": f"TSE:{code}", "d": [code, name, close, volume, change, rel_vol, atr, vwap, high, low, mcap, sector, exchange]}


SAMPLE_PAYLOAD = {
    "totalCount": 2,
    "data": [
        make_row("8918", 450, 20_000_000, 18.5, 3.2, 22.5, 440, 460, 400, 5_000_000_000, "Real Estate"),
        make_row("9432", 165, 15_000_000, -2.1, 0.8, 3.1, 166, 168, 163, 12_000_000_000_000, "Telecommunications"),
    ],
}


class ParseScanResponseTests(unittest.TestCase):
    def test_parses_rows_in_order(self):
        rows = tvs.parse_scan_response(SAMPLE_PAYLOAD)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["code"], "8918")
        self.assertEqual(rows[1]["code"], "9432")

    def test_maps_fields_correctly(self):
        row = tvs.parse_scan_response(SAMPLE_PAYLOAD)[0]
        self.assertEqual(row["price"], 450)
        self.assertEqual(row["change_pct"], 18.5)
        self.assertEqual(row["volume"], 20_000_000)
        self.assertEqual(row["relative_volume"], 3.2)
        self.assertEqual(row["vwap"], 440)
        self.assertEqual(row["exchange"], "TSE")
        self.assertEqual(row["sector"], "Real Estate")

    def test_computes_atr_pct_from_atr_and_close(self):
        row = tvs.parse_scan_response(SAMPLE_PAYLOAD)[0]
        self.assertAlmostEqual(row["atr_pct"], 22.5 / 450 * 100, places=2)

    def test_row_with_wrong_column_count_is_skipped_not_guessed(self):
        payload = {"data": [{"s": "TSE:1111", "d": ["1111", "Broken Co", 100]}]}
        self.assertEqual(tvs.parse_scan_response(payload), [])

    def test_missing_data_returns_empty_list_not_error(self):
        self.assertEqual(tvs.parse_scan_response({}), [])

    def test_atr_pct_none_when_close_zero_or_missing(self):
        payload = {"data": [make_row("0001", None, 100, 1.0, 1.0, 5.0, 100, 100, 100, 1, "Finance")]}
        row = tvs.parse_scan_response(payload)[0]
        self.assertIsNone(row["atr_pct"])


class AnnotateWatchedTests(unittest.TestCase):
    def test_marks_watched_and_unwatched_codes(self):
        rows = [{"code": "8918"}, {"code": "9999"}]
        annotated = tvs.annotate_watched(rows, {"8918"})
        self.assertTrue(annotated[0]["already_watched"])
        self.assertFalse(annotated[1]["already_watched"])

    def test_does_not_mutate_input_dicts(self):
        rows = [{"code": "8918"}]
        tvs.annotate_watched(rows, {"8918"})
        self.assertNotIn("already_watched", rows[0])


class LoadWatchedCodesTests(unittest.TestCase):
    def test_extracts_codes_from_ticker_field(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "watchlist.json"
            path.write_text(json.dumps({
                "stocks": {
                    "東京エレクトロン（8035）": {"ticker": "8035.T"},
                    "キオクシアHD（285A）": {"ticker": "285A.T"},
                }
            }), encoding="utf-8")
            codes = tvs.load_watched_codes(path)
        self.assertEqual(codes, {"8035", "285A"})

    def test_missing_file_returns_empty_set_not_error(self):
        codes = tvs.load_watched_codes(Path("/nonexistent/watchlist.json"))
        self.assertEqual(codes, set())


class BuildRankingsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"code": "A", "change_pct": 18.0, "relative_volume": 5.0, "atr_pct": 9.0, "price": 100, "volume": 1000},
            {"code": "B", "change_pct": -20.0, "relative_volume": 1.0, "atr_pct": 1.0, "price": 200, "volume": 5000},
            {"code": "C", "change_pct": 3.0, "relative_volume": 2.0, "atr_pct": 4.0, "price": 50, "volume": 10},
        ]

    def test_up_is_sorted_descending_by_change(self):
        rankings = tvs.build_rankings(self.rows, top_n=3)
        codes = [r["code"] for r in rankings["up"]["items"]]
        self.assertEqual(codes, ["A", "C", "B"])

    def test_down_is_sorted_ascending_by_change_catching_stop_low(self):
        rankings = tvs.build_rankings(self.rows, top_n=3)
        codes = [r["code"] for r in rankings["down"]["items"]]
        self.assertEqual(codes[0], "B")

    def test_top_n_limits_item_count(self):
        rankings = tvs.build_rankings(self.rows, top_n=1)
        self.assertEqual(len(rankings["up"]["items"]), 1)

    def test_turnover_uses_price_times_volume(self):
        rankings = tvs.build_rankings(self.rows, top_n=3)
        codes = [r["code"] for r in rankings["turnover"]["items"]]
        self.assertEqual(codes[0], "B")  # 200*5000 is the largest


if __name__ == "__main__":
    unittest.main()
