import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import research_lane_short_sale as lane
from scripts import ai_brain_research as brain

OFFICIAL_LINE = (
    "2026年10月5日 5,329,566 61.1% 2,829,702 32.4% 562,337 6.4% 8,721,605"
)


class ShortSaleLaneTests(unittest.TestCase):
    def test_parser_keeps_the_official_total(self):
        parsed = lane.parse_short_sale_text(OFFICIAL_LINE)
        self.assertEqual(parsed["session_date"], "2026-10-05")
        self.assertEqual(parsed["actual_order_million_yen"], 5329566)
        self.assertEqual(parsed["short_regulated_million_yen"], 2829702)
        self.assertEqual(parsed["short_unregulated_million_yen"], 562337)
        self.assertEqual(parsed["total_million_yen"], 8721605)
        self.assertEqual(
            parsed["actual_order_million_yen"]
            + parsed["short_regulated_million_yen"]
            + parsed["short_unregulated_million_yen"],
            parsed["total_million_yen"],
        )
        self.assertEqual(parsed["short_ratio"], 0.388924)

    def test_parser_rejects_a_broken_or_dateless_row(self):
        broken = "2026年10月5日 1 10.0% 1 10.0% 1 10.0% 4"
        self.assertRaises(ValueError, lane.parse_short_sale_text, broken)
        self.assertRaises(ValueError, lane.parse_short_sale_text, "合計だけ")
        impossible = "2026年2月31日 1 50.0% 1 50.0% 0 0.0% 2"
        self.assertRaises(ValueError, lane.parse_short_sale_text, impossible)

    def test_freshness_closes_future_and_old_sessions(self):
        session = "2026-10-05"
        self.assertEqual(lane.freshness(session, datetime(2026, 10, 5, tzinfo=lane.JST)), "FRESH")
        self.assertEqual(lane.freshness(session, datetime(2026, 10, 9, tzinfo=lane.JST)), "FRESH")
        self.assertEqual(lane.freshness(session, datetime(2026, 10, 10, tzinfo=lane.JST)), "STALE")
        self.assertEqual(lane.freshness(session, datetime(2026, 10, 4, tzinfo=lane.JST)), "STALE")

    def test_discovery_keeps_market_pdfs_only(self):
        html = (
            '<a href="261005-g.pdf">sector</a>'
            '<a href="/markets/statistics-equities/short-selling/t/261005-m.pdf">market</a>'
        )
        found = lane.discover_market_pdfs(html)
        self.assertEqual(found, [lane.PAGE + "t/261005-m.pdf"])

    def test_priority_covers_the_registry_and_fetches_only_the_first(self):
        ranked = [row["id"] for row in lane.LANE_PRIORITY]
        self.assertEqual(set(ranked), {item["id"] for item in brain.DATA_LANE})
        self.assertEqual(len(ranked), 17)
        self.assertEqual([row["rank"] for row in lane.LANE_PRIORITY], list(range(1, 18)))
        for row in lane.LANE_PRIORITY:
            self.assertEqual(
                row["score"],
                row["contribution"] + row["license"] + row["history"] + row["speed"] + row["available_at"],
            )
        self.assertEqual(
            [row["id"] for row in lane.FETCH_RANK],
            ["short_sale_ratio", "investor_futures_flow", "arbitrage_balance"],
        )
        self.assertEqual(
            [row["id"] for row in lane.LANE_PRIORITY if row["fetch_this_turn"]],
            ["short_sale_ratio"],
        )
        for key in ("nt_ratio", "futures_options_positioning", "jpx_nikkei_mid_small", "dex", "tradingview_wide"):
            self.assertTrue(lane.NOT_FETCHED_BECAUSE[key])

    def test_stored_observation_is_fetched_and_not_a_live_sample(self):
        record = json.loads(lane.LATEST.read_text(encoding="utf-8"))
        observed = datetime.fromisoformat(record["fetched_at"])
        self.assertEqual(record["available_at"], record["fetched_at"])
        self.assertNotIn("T00:00:00", record["available_at"])
        self.assertEqual(record["session_date"], "2026-10-05")
        self.assertEqual(record["short_ratio"], 0.388924)
        self.assertEqual(record["total_million_yen"], 8721605)
        self.assertFalse(record["trading_adoption"])
        self.assertFalse(record["real_submit_allowed"])
        self.assertFalse(record["counts_as_live_sample"])
        self.assertFalse(record["promotion_candidate"])
        self.assertEqual(record["source_stage"], "OFFICIAL_PUBLIC")
        self.assertTrue(record["source"].endswith("261005-m.pdf"))
        self.assertIn("trading_adoption=false", record["license_note"])
        blob = (lane.RAW / f"{record['sha256']}.pdf").read_bytes()
        self.assertEqual(hashlib.sha256(blob).hexdigest(), record["sha256"])
        self.assertTrue(blob.startswith(b"%PDF"))
        loaded = lane.load_latest(now=observed)
        self.assertEqual(loaded["fetch_status"], "FETCHED")
        self.assertEqual(loaded["freshness"], "FRESH")
        self.assertEqual(loaded["short_ratio_for_research"], 0.388924)
        aged = lane.load_latest(now=observed + timedelta(days=5))
        self.assertEqual(aged["fetch_status"], "FETCHED")
        self.assertEqual(aged["freshness"], "STALE")
        self.assertIsNone(aged["short_ratio_for_research"])
        sessions = [json.loads(line) for line in lane.HISTORY.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["session_date"] for row in sessions], ["2026-10-01", "2026-10-02", "2026-10-05"])
        old = sessions[0]
        self.assertEqual(old["freshness"], "STALE")
        self.assertIsNone(old["short_ratio_for_research"])
        self.assertEqual(old["short_ratio"], 0.388682)

    def test_research_layer_can_read_it_without_adopting_it(self):
        lane_rows = brain.research_data_lane()
        self.assertEqual(
            {item["id"] for item in lane_rows if item["fetch_status"] == "FETCHED"},
            {"short_sale_ratio"},
        )
        item = next(row for row in lane_rows if row["id"] == "short_sale_ratio")
        self.assertFalse(item["trading_adoption"])
        self.assertFalse(item["real_submit_allowed"])
        self.assertFalse(item["counts_as_live_sample"])
        self.assertFalse(item["promotion_candidate"])
        self.assertEqual(item["source_stage"], "OFFICIAL_PUBLIC")
        self.assertEqual(item["available_at"], item["fetched_at"])
        self.assertTrue(item["source"].endswith("-m.pdf"))
        self.assertIn("売買条件には使わない", item["license_note"])
        if item["freshness"] == "FRESH":
            self.assertEqual(item["short_ratio_for_research"], 0.388924)
        else:
            self.assertIsNone(item["short_ratio_for_research"])
        self.assertTrue(all(row["trading_adoption"] is False for row in lane_rows))
        self.assertTrue(all(row["real_submit_allowed"] is False for row in lane_rows))

    def test_malformed_store_does_not_invent_a_ratio(self):
        record = json.loads(lane.LATEST.read_text(encoding="utf-8"))
        blob = (lane.RAW / f"{record['sha256']}.pdf").read_bytes()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw"
            raw.mkdir()
            (raw / f"{record['sha256']}.pdf").write_bytes(blob)
            latest = root / "latest.json"
            tampered = dict(record, short_ratio=0.5)
            latest.write_text(json.dumps(tampered), encoding="utf-8")
            with patch.object(lane, "LATEST", latest), patch.object(lane, "RAW", raw):
                closed = lane.load_latest()
                self.assertEqual(closed["fetch_status"], "FAIL_CLOSED")
                self.assertIsNone(closed["short_ratio"])
                self.assertIsNone(closed["short_ratio_for_research"])
                self.assertFalse(closed["trading_adoption"])
                rows = brain.research_data_lane()
                item = next(row for row in rows if row["id"] == "short_sale_ratio")
                self.assertEqual(item["fetch_status"], "FAIL_CLOSED")
                self.assertIsNone(item["short_ratio_for_research"])
                self.assertFalse(item["trading_adoption"])
            flipped = bytearray(blob)
            flipped[20] ^= 0x01
            (raw / f"{record['sha256']}.pdf").write_bytes(bytes(flipped))
            latest.write_text(json.dumps(record), encoding="utf-8")
            with patch.object(lane, "LATEST", latest), patch.object(lane, "RAW", raw):
                self.assertEqual(lane.load_latest()["fetch_status"], "FAIL_CLOSED")
            latest.write_text(json.dumps(dict(record, source_stage="SYNTHETIC/REPLAY")), encoding="utf-8")
            (raw / f"{record['sha256']}.pdf").write_bytes(blob)
            with patch.object(lane, "LATEST", latest), patch.object(lane, "RAW", raw):
                self.assertEqual(lane.load_latest()["fetch_status"], "FAIL_CLOSED")
            missing = root / "absent.json"
            with patch.object(lane, "LATEST", missing):
                empty = lane.load_latest()
            self.assertEqual(empty["fetch_status"], "NOT_FETCHED")
            self.assertIsNone(empty["short_ratio"])

    def test_repeat_store_keeps_the_first_observation(self):
        record = json.loads(lane.LATEST.read_text(encoding="utf-8"))
        blob = (lane.RAW / f"{record['sha256']}.pdf").read_bytes()
        first = datetime(2026, 10, 6, 1, 0, tzinfo=lane.JST)
        later = first + timedelta(hours=3)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw"
            history = root / "history.jsonl"
            latest = root / "latest.json"
            with patch.object(lane, "RAW", raw), patch.object(lane, "HISTORY", history), patch.object(lane, "LATEST", latest):
                built = lane.build_record(blob, record["source"], first)
                lane.write_store([built], {built["sha256"]: blob})
                again = lane.build_record(blob, record["source"], later)
                stored = lane.write_store([again], {again["sha256"]: blob})
            self.assertEqual(stored["available_at"], built["available_at"])
            self.assertEqual(stored["fetched_at"], built["fetched_at"])
            self.assertNotEqual(again["fetched_at"], built["fetched_at"])

    def test_module_does_not_submit(self):
        text = (ROOT / "scripts" / "research_lane_short_sale.py").read_text(encoding="utf-8")
        self.assertNotIn("submit_shadow_order", text)
        self.assertNotIn("shadow_execution", text)
        self.assertNotIn("real_submit_allowed = True", text)
        self.assertNotIn('real_submit_allowed"] = True', text)


if __name__ == "__main__":
    unittest.main()
