"""JPX 銘柄別信用取引残高 (all issues, daily PDF) adapter and its evidence bundle wiring.

Offline only: the PDF text lines are written here in the layout of the official
file (header with the as-of date, issue blocks of code / ISIN / fourteen figures,
a block cut by a page header, an ETF block with "*" ratios, a block whose totals
do not add up). Every figure and code below is synthetic, not a real JPX balance.
No network, no API key, no paid call.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import agent_sdk_coordination_pilot as pilot
from scripts import agent_sdk_evidence_bundle as bundler
from scripts import agent_sdk_jpx_margin_all_ingest as jpx_all

NOW = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)  # 17:00 JST, after the 16:00 publication
FILE_URL = "https://www.jpx.co.jp/markets/statistics-equities/margin/tvdivq0000001rnl-att/20261020_mtall.pdf"
HEADER = ["2026/10/20 申込み現在", "東京証券取引所株式部", "（単位：一株、一円）", "2026/10/21", "売残高", "前日比"]


def block(code, figures, name="銘柄"):
    return ["B", name, "プライム", "貸", code, "JP3000000000 株数 Shs. "] + figures


# Synthetic: totals = negotiable + standardized for both balances and both changes.
LINES = HEADER + block("123A0", ["2,000,000", "▲ 500,000", "0.1%", "30,000,000", "▲ 10,000,000", "1.0%",
                                 "400,000", "▲ 100,000", "1,600,000", "▲ 400,000",
                                 "10,000,000", "▲ 4,000,000", "20,000,000", "▲ 6,000,000"], "テスト銘柄Ａ") + \
    ["TEST A", "123A0", "JP3000000000 金額 Val. ", "1,000", "2,000"] + \
    block("99900", ["300,000", "▲ 100,000", "0.0%", "6,000,000"]) + HEADER + \
    ["▲ 5,000,000", "0.3%", "100,000", "▲ 40,000", "200,000", "▲ 60,000",                 # cut by a page header
     "2,000,000", "▲ 3,000,000", "4,000,000", "▲ 2,000,000"] + \
    block("99950", ["5,000", "▲ 4,000", "*", "30,000", "▲ 20,000", "*", "1,000", "0", "4,000", "▲ 4,000",
                    "20,000", "▲ 15,000", "10,000", "▲ 5,000"]) + \
    block("99990", ["100", "0", "0.0%", "200", "0", "0.0%", "1", "0", "1", "0", "100", "0", "100", "0"])  # 1+1 != 100


class Parse(unittest.TestCase):
    def test_blocks_page_breaks_and_checksums(self):
        got = jpx_all.parse_lines(LINES, observed_at=NOW)
        self.assertEqual(got["as_of_date"], "2026-10-20")
        self.assertEqual(sorted(got["issues"]), ["123A", "9990", "9995"])
        self.assertEqual(got["dropped_blocks"], 1)   # 9999 does not add up: dropped, never guessed
        k = got["issues"]["123A"]
        self.assertEqual((k["sales"], k["sales_change"], k["purchases"], k["purchases_change"]),
                         (2000000, -500000, 30000000, -10000000))
        self.assertEqual(got["issues"]["9990"]["purchases_change"], -5000000)

    def test_stale_or_future_file_is_refused(self):
        for when in (datetime(2026, 11, 5, tzinfo=timezone.utc), datetime(2026, 10, 19, tzinfo=timezone.utc)):
            with self.assertRaises(jpx_all.MarginBlocked):
                jpx_all.parse_lines(LINES, observed_at=when)
        with self.assertRaises(jpx_all.MarginBlocked):
            jpx_all.parse_lines(["no date here"], observed_at=NOW)

    def test_latest_link_and_codes(self):
        html = ('<a href="/markets/statistics-equities/margin/tvdivq0000001rnl-att/20261019_mtall.pdf">x</a>'
                '<a href="/markets/statistics-equities/margin/tvdivq0000001rnl-att/20261020_mtall.pdf">y</a>').encode()
        self.assertEqual(jpx_all.latest_file_url(html), FILE_URL)
        self.assertEqual(jpx_all.parse_codes("9990, 123a,9990"), ["9990", "123A"])   # priority order kept
        for bad in ("", "28A", "9990;", ",".join(["1000"] * 151)):
            with self.assertRaises(jpx_all.MarginBlocked):
                jpx_all.parse_codes(bad if bad != ",".join(["1000"] * 151) else ",".join(str(1000 + i) for i in range(151)))


class Sources(unittest.TestCase):
    def test_compact_records_valid_for_the_analysts(self):
        parsed = jpx_all.parse_lines(LINES, observed_at=NOW)
        rows = jpx_all.build_sources(parsed, ["9990", "123A", "1111", "9995"], FILE_URL, observed_at=NOW)
        self.assertEqual(len(rows), 1)
        s = rows[0]["summary"]
        self.assertTrue(s.startswith("JPX銘柄別信用取引残高 2026-10-20申込み現在"))
        self.assertLess(s.index("9990"), s.index("123A"))           # the caller's priority order
        self.assertIn("123A 売200.0万(-50.0万) 買3,000.0万(-1,000.0万) 倍15.00", s)
        self.assertNotIn("1111", s)                                  # not in the file: no record, no guess
        self.assertLessEqual(len(s), 400)
        self.assertEqual((rows[0]["source_type"], rows[0]["role"]), ("OFFICIAL_STATISTICS_FILE", "supply_sq"))
        pilot.validate_snapshot({"schema_version": pilot.SCHEMA, "run_id": "jpx_all_test", "sources": rows}, NOW)

    def test_many_issues_split_into_records_under_400(self):
        issues = {str(1000 + i): {"code": str(1000 + i), "sales": 12345678, "sales_change": -1234567,
                                  "purchases": 98765432, "purchases_change": -9876543} for i in range(100)}
        rows = jpx_all.build_sources({"as_of_date": "2026-10-20", "issues": issues}, list(issues), FILE_URL, observed_at=NOW)
        self.assertGreaterEqual(len(rows), 15)
        self.assertEqual(sum(r["summary"].count(" 倍") for r in rows), 100)   # every issue kept, none cut
        self.assertTrue(all(len(r["summary"]) <= 400 and r["summary"].endswith("売買シグナルではない") for r in rows))


class BrainCache(unittest.TestCase):
    def test_cache_keeps_every_valid_issue(self):
        parsed = jpx_all.parse_lines(LINES, observed_at=NOW)
        cache = jpx_all.build_cache(parsed, FILE_URL, observed_at=NOW)
        self.assertEqual((cache["schema_version"], cache["as_of_date"], cache["issue_count"], cache["dropped_blocks"]),
                         ("100b-v10-jpx-margin-all-cache-v1", "2026-10-20", 3, 1))
        self.assertEqual(cache["issues"]["123A"], {"sales": 2000000, "sales_change": -500000,
                                                  "purchases": 30000000, "purchases_change": -10000000})
        self.assertIs(cache["real_submit_allowed"], False)


class Bundle(unittest.TestCase):
    def test_bundle_option_and_boj_trim(self):
        parsed = jpx_all.parse_lines(LINES, observed_at=NOW)
        jpx_rows = jpx_all.build_sources(parsed, ["123A"], FILE_URL, observed_at=NOW)
        boj_rows = [dict(jpx_rows[0], source_id="boj_%d" % i, role="pre_next", source_type="OFFICIAL_RSS_HEADLINE",
                         data_status="PUBLICATION_TIME_VERIFIED", summary="headline %d" % i) for i in range(5)]
        with tempfile.TemporaryDirectory() as d, \
                patch.object(bundler.jpx_all, "fetch_sources", return_value=(jpx_rows, {})), \
                patch.object(bundler.boj, "fetch_official_feed", return_value=b""), \
                patch.object(bundler.boj, "build_snapshot", return_value={"sources": boj_rows}), \
                patch.object(bundler, "datetime") as dt:
            dt.now.return_value = NOW
            out = Path(d) / "e.json"
            code = bundler.main(["--fetch", "--run-id", "jpx_all_bundle", "--output", str(out), "--boj",
                                 "--boj-per-role", "2", "--jpx-margin-all-codes", "123A,9990"])
            self.assertEqual(code, 0)
            doc = json.loads(out.read_text(encoding="utf-8"))
        kinds = [r["source_type"] for r in doc["sources"]]
        self.assertEqual(kinds, ["OFFICIAL_STATISTICS_FILE", "OFFICIAL_RSS_HEADLINE", "OFFICIAL_RSS_HEADLINE"])


if __name__ == "__main__":
    unittest.main()
