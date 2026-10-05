import json
import unittest
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import Workbook

from scripts import research_lane_arbitrage as lane

ROOT = Path(__file__).resolve().parents[1]
BROKER = "架空証券アルファ"


def _sheet(sell=100, buy=40, company_buy=None, short_far=2, change="▲4"):
    book = Workbook()
    sheet = book.active
    sheet["C1"] = "裁定取引に係る現物株式の売買及び現物ポジション（全取引参加者報告合計）"
    sheet["M2"] = "2026年10月5日"
    sheet["C4"] = "１．裁定取引に係る現物株式の売買（10月1日売買分）"
    sheet["O4"] = "（単位：千株）"
    sheet["E5"] = "売付け"
    sheet["J5"] = "買付け"
    sheet["C6"] = "株数"
    sheet["E6"] = sell
    sheet["J6"] = buy
    sheet["C8"] = "２．裁定取引に係る現物ポジション（10月1日現在）"
    sheet["E10"] = "当限"
    sheet["F10"] = "翌限以降"
    sheet["H10"] = "合計"
    sheet["J10"] = "当限"
    sheet["L10"] = "翌限以降"
    sheet["N10"] = "合計"
    sheet["C11"] = "株数"
    sheet["E11"] = 10
    sheet["F11"] = short_far
    sheet["H11"] = 12
    sheet["J11"] = 80
    sheet["L11"] = 3
    sheet["N11"] = 83
    sheet["D12"] = "前日比"
    sheet["E12"] = 1
    sheet["F12"] = 0
    sheet["H12"] = 1
    sheet["J12"] = change
    sheet["L12"] = 1
    sheet["N12"] = -3
    sheet["C16"] = "当限は、2026年12月限までを含む。"
    sheet["C30"] = "取引参加者別裁定取引の状況"
    sheet["C34"] = "証券会社名"
    sheet["G34"] = "売付株数"
    sheet["I34"] = "買付株数"
    sheet["C36"] = BROKER
    sheet["G36"] = sell
    sheet["I36"] = buy if company_buy is None else company_buy
    sheet["C52"] = "全社合計"
    sheet["G52"] = sell
    sheet["I52"] = buy if company_buy is None else company_buy
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


class ArbitrageLaneTests(unittest.TestCase):
    def test_market_total_drops_the_participant_name(self):
        blob = _sheet()
        parsed = lane.parse_arbitrage_workbook(blob, "https://www.jpx.co.jp/x/261001.xls")
        encoded = json.dumps(parsed, ensure_ascii=False)
        self.assertNotIn(BROKER, encoded)
        self.assertNotIn("証券会社名", encoded)
        self.assertEqual(parsed["session_date"], "2026-10-01")
        self.assertEqual(parsed["sell_shares_thousand"], 100)
        self.assertEqual(parsed["buy_shares_thousand"], 40)
        self.assertEqual(parsed["long_position_total_thousand"], 83)
        self.assertEqual(parsed["long_change_near_thousand"], -4)
        self.assertEqual(parsed["sheet_label_date"], "2026-10-05")
        self.assertFalse(parsed["raw_retained"])
        self.assertFalse(parsed["participant_names_retained"])
        with self.assertRaises(ValueError):
            lane.parse_arbitrage_workbook(_sheet(company_buy=41), "https://www.jpx.co.jp/x/261001.xls")
        with self.assertRaises(ValueError):
            lane.parse_arbitrage_workbook(_sheet(short_far=9), "https://www.jpx.co.jp/x/261001.xls")
        with self.assertRaises(ValueError):
            lane.parse_arbitrage_workbook(blob, "https://www.jpx.co.jp/x/261002.xls")

    def test_stored_total_is_fetched_without_the_workbook(self):
        record = json.loads(lane.LATEST.read_text(encoding="utf-8"))
        self.assertEqual(record["session_date"], "2026-10-01")
        self.assertEqual(record["sell_shares_thousand"], 64563)
        self.assertEqual(record["buy_shares_thousand"], 8980)
        self.assertEqual(record["long_position_total_thousand"], 849191)
        self.assertEqual(record["short_position_total_thousand"], 7985)
        self.assertIsNone(record["long_position_total_for_research"])
        self.assertEqual(record["freshness"], "STALE")
        self.assertEqual(record["business_day_gap"], 3)
        self.assertEqual(record["published_at"], "2026-10-05T16:00:31+09:00")
        self.assertEqual(record["published_at_basis"], "http_last_modified")
        self.assertNotIn("T", record["sheet_label_date"])
        self.assertEqual(record["sheet_label_date"], "2026-10-05")
        self.assertEqual(record["first_seen_at"], "2026-10-06T02:01:58.033482+09:00")
        self.assertEqual(record["sha256"], "004234bbfe70c28477815aece51a98db0e74923f84c2855a7aa27a5846d0c519")
        self.assertFalse(record["raw_retained"])
        self.assertFalse(record["trading_adoption"])
        self.assertFalse(record["real_submit_allowed"])
        self.assertEqual(record["source_stage"], "OFFICIAL_PUBLIC")
        encoded = lane.HISTORY.read_text(encoding="utf-8") + lane.LATEST.read_text(encoding="utf-8")
        self.assertNotIn("証券会社名", encoded)
        self.assertNotIn("取引参加者", encoded)
        self.assertFalse(any(path.suffix.lower() in {".xls", ".xlsx", ".pdf"} for path in lane.STORE.rglob("*")))
        sessions = [json.loads(line)["session_date"] for line in lane.HISTORY.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sessions[0], "2026-09-15")
        self.assertEqual(sessions[-1], "2026-10-01")
        self.assertEqual(len(sessions), 10)
        loaded = lane.load_latest(now=datetime.fromisoformat(record["first_seen_at"]))
        self.assertEqual(loaded["fetch_status"], "FETCHED")
        self.assertEqual(loaded["freshness"], "STALE")
        self.assertIsNone(loaded["long_position_total_for_research"])
        fresh_clock = datetime(2026, 10, 2, 12, 0, tzinfo=lane.JST)
        fresh = lane.load_latest(now=fresh_clock)
        self.assertEqual(fresh["fetch_status"], "FETCHED")
        self.assertIsNone(fresh["long_position_total_for_research"])

    def test_a_raw_workbook_next_to_the_store_fails_closed(self):
        record = json.loads(lane.LATEST.read_text(encoding="utf-8"))
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest = root / "latest.json"
            history = root / "history.jsonl"
            latest.write_text(json.dumps(record), encoding="utf-8")
            history.write_text(json.dumps(record) + "\n", encoding="utf-8")
            (root / "kept.xls").write_bytes(b"not-a-workbook")
            with patch.object(lane, "STORE", root), patch.object(lane, "LATEST", latest), patch.object(lane, "HISTORY", history):
                closed = lane.load_latest()
            self.assertEqual(closed["fetch_status"], "FAIL_CLOSED")
            self.assertIsNone(closed["long_position_total_for_research"])
            self.assertFalse(closed["trading_adoption"])
