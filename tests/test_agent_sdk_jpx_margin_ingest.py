"""JPX 日々公表銘柄等信用取引残高 adapter and the supply_sq path end to end.

Offline only: the workbook is generated here in the layout of the official
file (title, as-of / publication date row, two header rows, issue rows with
and without the 株 flag, an ETF row with "*" ratios, phonetic guides in shared
strings). No network, no API key, no paid call.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import agent_sdk_brain_handoff as bridge
from scripts import agent_sdk_coordination_pilot as pilot
from scripts import agent_sdk_evidence_bundle as bundler
from scripts import agent_sdk_jpx_margin_ingest as jpx
from scripts import agent_sdk_public_feed_ingest as boj
from scripts import v10_brain_agent_research_receiver as receiver

NOW = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)  # 17:00 JST, after the 16:00 publication
FILE_URL = "https://www.jpx.co.jp/markets/statistics-equities/margin/tvdivq0000001r92-att/20261020_mtdaily.xlsx"


def col(i):
    s = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        s = chr(65 + rem) + s
    return s


def workbook(rows, *, dtd=False):
    """Minimal xlsx in the official layout; strings go to sharedStrings with a phonetic run."""
    strings, xml_rows = [], []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            if value == "" or value is None:
                continue
            ref = col(c) + str(r)
            if isinstance(value, (int, float)):
                cells.append('<c r="%s"><v>%s</v></c>' % (ref, value))
            else:
                strings.append(value)
                cells.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, len(strings) - 1))
        xml_rows.append('<row r="%d">%s</row>' % (r, "".join(cells)))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    sst = "".join('<si><t>%s</t><rPh sb="0" eb="1"><t>ヨミ</t></rPh></si>' % s.replace("&", "&amp;") for s in strings)
    head = '<!DOCTYPE x [<!ENTITY a "b">]>' if dtd else ""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook %s %s><sheets><sheet name="s" sheetId="1" r:id="rId1"/></sheets></workbook>' % (ns, rel))
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", head + '<sst %s>%s</sst>' % (ns, sst))
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet %s><sheetData>%s</sheetData></worksheet>' % (ns, "".join(xml_rows)))
    return buf.getvalue()


def official_rows(as_of="2026/10/20", published="2026/10/21"):
    return [
        ["", "1 銘柄欄:"],
        ["日々公表銘柄等信用取引残高"],
        ["Outstanding Margin Trading of Issues Subject to Daily Publication"],
        ["", as_of, "", "申込み現在"] + [""] * 17 + [published, "(Unit:1Share)"],
        ["", "", "", "", "市場", "銘柄種別", "コード", "新証券コード", "売残高 Outstanding Sales", "", "", "買残高 Outstanding Purchases", "", "", "取組比率"],
        ["B", "規", "株", "カウリス　普通株式", "グロース", "貸", "153A0", "JP3205750007", 27700.0, -27000.0, 0.4, 176100.0, -118000.0, 2.7, 15.7, 0, 0],
        ["B", "日", "", "キオクシアホールディングス　普通株式", "プライム", "貸", "285A0", "JP3165650007", 4796300.0, -122000.0, 5.7, 1.70773E7, -4500.0, 20.4, 28.1, 0, 0],
        ["J", "喚", "", "東証グロース２５０ＥＴＦ　受益証券", "投信等", "貸", "25160", "JP3048700003", 585480, -10180, "*", 1094740, -50960, "*", 53.5],
        ["B", "日", "", "壊れた行　普通株式", "プライム", "制", "99990", "JP3999999999", "n/a", 1, 1, 1, 1, 1, 1],
    ]


class Parse(unittest.TestCase):
    def parse(self, rows=None, now=NOW):
        return jpx.parse_margin(jpx.read_xlsx_rows(workbook(rows or official_rows())), observed_at=now)

    def test_dates_and_balances_from_the_official_layout(self):
        got = self.parse()
        self.assertEqual((got["as_of_date"], got["published_date"]), ("2026-10-20", "2026-10-21"))
        k = got["issues"]["285A"]
        self.assertEqual((k["sales"], k["sales_change"], k["purchases"], k["purchases_change"], k["sale_purchase_ratio"]),
                         (4796300, -122000, 17077300, -4500, 28.1))
        self.assertEqual(k["name"], "キオクシアホールディングス　普通株式")  # phonetic guide not mixed in
        self.assertIn("153A", got["issues"])      # row with the 株 flag column
        self.assertIn("2516", got["issues"])      # ETF with "*" ratios
        self.assertNotIn("9999", got["issues"])   # malformed number: skipped, not guessed

    def test_future_or_stale_publication_is_blocked(self):
        with self.assertRaisesRegex(jpx.MarginBlocked, "STALE_OR_FUTURE"):
            self.parse(official_rows(published="2026/10/22"))
        with self.assertRaisesRegex(jpx.MarginBlocked, "STALE_OR_FUTURE"):
            self.parse(now=NOW + timedelta(days=10))
        with self.assertRaisesRegex(jpx.MarginBlocked, "STALE_OR_FUTURE"):
            self.parse(official_rows(as_of="2026/10/22", published="2026/10/21"))

    def test_unknown_layout_is_blocked(self):
        rows = official_rows()
        rows[1] = ["別の資料"]
        with self.assertRaisesRegex(jpx.MarginBlocked, "TITLE_NOT_FOUND"):
            self.parse(rows)
        rows = [r for r in official_rows() if "申込み現在" not in r]
        with self.assertRaisesRegex(jpx.MarginBlocked, "DATES_NOT_FOUND"):
            self.parse(rows)

    def test_dtd_in_workbook_is_refused(self):
        with self.assertRaisesRegex(jpx.MarginBlocked, "DTD_FORBIDDEN"):
            jpx.read_xlsx_rows(workbook(official_rows(), dtd=True))

    def test_only_the_official_margin_path_is_fetched(self):
        for url in ("https://evil.example/markets/statistics-equities/margin/a.xlsx",
                    "http://www.jpx.co.jp/markets/statistics-equities/margin/a.xlsx",
                    "https://www.jpx.co.jp/other/a.xlsx",
                    "https://www.jpx.co.jp/markets/statistics-equities/margin/a.xlsx?x=1"):
            with self.subTest(url=url), self.assertRaisesRegex(jpx.MarginBlocked, "NOT_ALLOWLISTED"):
                jpx._get(url, 10)

    def test_latest_link_is_taken_from_the_index_page(self):
        html = ('<a href="/markets/statistics-equities/margin/a-att/20261019_mtdaily.xlsx">x</a>'
                '<a href="/markets/statistics-equities/margin/b-att/20261020_mtdaily.xlsx">y</a>'
                '<a href="https://evil.example/markets/statistics-equities/margin/c-att/20261030_mtdaily.xlsx">z</a>').encode()
        self.assertEqual(jpx.latest_file_url(html),
                         "https://www.jpx.co.jp/markets/statistics-equities/margin/b-att/20261020_mtdaily.xlsx")
        with self.assertRaisesRegex(jpx.MarginBlocked, "LINK_NOT_FOUND"):
            jpx.latest_file_url(b"<html></html>")


class Evidence(unittest.TestCase):
    def test_sources_follow_the_v2_time_contract(self):
        parsed = jpx.parse_margin(jpx.read_xlsx_rows(workbook(official_rows())), observed_at=NOW)
        rows = jpx.build_sources(parsed, ["285A", "8035"], FILE_URL, observed_at=NOW)
        self.assertEqual(len(rows), 1)  # 8035 is not a daily-publication issue in this file: no record
        r = rows[0]
        self.assertEqual((r["role"], r["source_type"], r["data_status"]),
                         ("supply_sq", "OFFICIAL_STATISTICS_FILE", "DATE_ONLY_OBSERVED_AT_FETCH"))
        self.assertEqual(r["as_of"], r["available_at"])
        self.assertEqual(r["available_at"], r["fetched_at"])
        self.assertIn("全銘柄の日次信用残ではない", r["summary"])
        doc = {"schema_version": pilot.SCHEMA, "run_id": "jpx_margin_test_01", "sources": rows}
        self.assertEqual(len(pilot.validate_snapshot(doc, NOW)["sources"]), 1)

    def test_codes_are_validated(self):
        self.assertEqual(jpx.parse_codes("285a, 8035,285A"), ["285A", "8035"])
        for bad in ("", "28", "285A;rm", ",".join(["1000"] * 31)):
            with self.subTest(bad=bad), self.assertRaises(jpx.MarginBlocked):
                jpx.parse_codes(bad)

    def test_bundle_keeps_working_when_one_adapter_fails(self):
        parsed = jpx.parse_margin(jpx.read_xlsx_rows(workbook(official_rows())), observed_at=NOW)
        rows = jpx.build_sources(parsed, ["285A"], FILE_URL, observed_at=NOW)
        doc, status = bundler.bundle("bundle_test_0001", {"boj": boj.EvidenceBlocked("RSS_FETCH_UNAVAILABLE"),
                                                          "jpx_margin": rows}, now=NOW)
        self.assertEqual(status, {"boj": "BLOCKED:RSS_FETCH_UNAVAILABLE", "jpx_margin": "OK:1"})
        self.assertEqual({r["role"] for r in doc["sources"]}, {"supply_sq"})
        with self.assertRaisesRegex(boj.EvidenceBlocked, "NO_EVIDENCE_FROM_ANY_ADAPTER"):
            bundler.bundle("bundle_test_0002", {"boj": boj.EvidenceBlocked("X")}, now=NOW)


class SupplyPathEndToEnd(unittest.TestCase):
    """JPX file -> evidence -> supply_sq analysis citing it -> signed envelope ->
    Brain receipt and ACK -> display shows a usable, sourced supply_sq report."""

    def setUp(self):
        env = patch.dict(os.environ, {bridge.KEY_ENV: "6b" * 32, receiver.RECEIVER_KEY_ENV: "9c" * 32})
        env.start()
        self.addCleanup(env.stop)
        tmp = tempfile.mkdtemp(prefix="v10-jpx-e2e-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.inbox = Path(tmp) / "100億PROJECT" / "受け箱"
        self.inbox.mkdir(parents=True)

    def test_supply_report_reaches_the_display_with_its_source(self):
        parsed = jpx.parse_margin(jpx.read_xlsx_rows(workbook(official_rows())), observed_at=NOW)
        doc = {"schema_version": pilot.SCHEMA, "run_id": "jpx_e2e_20261021_01",
               "sources": jpx.build_sources(parsed, ["285A"], FILE_URL, observed_at=NOW)}

        async def analyst(role, prompt):
            if role == "progress_coordinator":
                return {"summary": "Synthetic review of the JPX margin evidence", "conflicts": [], "next_checks": []}
            ids = [s["source_id"] for s in json.loads(prompt)["sources"]]
            return {"role": role, "status": "WATCH", "evidence_ids": ids,
                    "hypothesis": "Synthetic: margin purchases high relative to sales",
                    "conditions": "Holds while the next daily publication shows the same direction",
                    "invalidation": "Withdrawn if the issue leaves daily publication or purchases fall"}

        result = asyncio.run(pilot.coordinate(doc, analyst, now=NOW + timedelta(minutes=1),
                                              target_at="2026-10-22T08:30:00+09:00", slot="supply_1730"))
        result["state"] = "OFFLINE_SYNTHETIC_NO_API_CALL"
        bridge.produce(doc, result, private_dir=self.inbox, now=NOW + timedelta(minutes=2))
        out = receiver.receive_inbox(self.inbox, now=NOW + timedelta(minutes=3))
        self.assertEqual([r["state"] for r in out["results"]], ["RECEIVED"])
        view = json.loads((self.inbox / receiver.DISPLAY_NAME).read_text("utf-8"))
        rep = {r["role"]: r for r in view["runs"][0]["reports"]}["supply_sq"]
        self.assertEqual((rep["status"], rep["usable"]), ("WATCH", True))
        self.assertEqual(rep["evidence"][0]["source_name"], jpx.SOURCE_NAME)
        self.assertEqual(rep["evidence"][0]["source_url"], FILE_URL)
        self.assertEqual(rep["evidence"][0]["data_status"], "DATE_ONLY_OBSERVED_AT_FETCH")
        others = {r["role"]: r["not_usable_reason"] for r in view["runs"][0]["reports"] if r["role"] != "supply_sq"}
        self.assertEqual(others, {"premarket": "NO_DATA", "pre_next": "NO_DATA", "revenue_hunter": "NO_DATA"})
        self.assertIs(view["real_submit_allowed"], False)


if __name__ == "__main__":
    unittest.main()
