import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 5, 16, 20, 0, tzinfo=JST)


def _load():
    spec = importlib.util.spec_from_file_location("p0_shadow_penetration", ROOT / "scripts" / "p0_shadow_penetration.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pen = _load()


def _payload(price=19120, symbol="285A.T", **overrides):
    diag = {
        "symbol": symbol,
        "current_price": price,
        "source_timestamp": "16:19:58",
        "price_source_status": "OK",
        "source_mode": "MS2_RSS_WORKBOOK",
        "workbook_name": "Kioxia_MS2_RSS_Live_Signals.xlsx",
        "workbook_identity_verified": True,
        "data_conflict": False,
        "duplicate_collector": False,
        "duplicate_watcher": False,
        "collector_count": 1,
        "watcher_count": 1,
        "stale_reason": "",
        "real_submit_allowed": False,
        "live_values_available": True,
    }
    body = {
        "updated_at": "2026-10-05 16:20:00",
        "source": "MarketSpeed II RSS / local PC",
        "source_mode": "MS2_RSS_WORKBOOK",
        "stale": False,
        "data_conflict": False,
        "price_source_status": "OK",
        "live_values_available": True,
        "real_submit_allowed": False,
        "live_price_diagnostics": diag,
        "all_targets": [{
            "ticker": symbol,
            "price": price,
            "source_timestamp": "16:19:58",
            "signal": "監視",
            "data": "LIVE",
        }],
    }
    body.update(overrides)
    return body


class ShadowPenetrationTests(unittest.TestCase):
    def test_matching_285a_price_reaches_strategy_and_shadow(self):
        result = pen.evaluate_chain(_payload(), _payload(), now=NOW, file_mtime=NOW - timedelta(seconds=2))
        self.assertTrue(result["ok"], result["reasons"])
        self.assertEqual(result["symbol"], "285A.T")
        self.assertEqual(result["price"], 19120)
        self.assertEqual(result["strategy_price"], 19120)
        self.assertNotEqual(result["shadow_state"], "PAUSED_FAIL_CLOSED")
        self.assertFalse(result["real_submit_allowed"])

    def test_gateway_price_mismatch_stale_wrong_symbol_and_duplicate_fail_closed(self):
        mismatch = pen.evaluate_chain(_payload(), _payload(price=19121), now=NOW, file_mtime=NOW)
        self.assertIn("COLLECTOR_GATEWAY_PRICE_MISMATCH", mismatch["reasons"])
        self.assertFalse(mismatch["ok"])
        wrong = pen.evaluate_chain(_payload(symbol="8035.T"), _payload(symbol="8035.T"), now=NOW, file_mtime=NOW)
        self.assertIn("WRONG_SYMBOL_MAPPING", wrong["reasons"])
        stale = _payload()
        stale["stale"] = True
        stale["live_price_diagnostics"]["price_source_status"] = "STALE"
        closed = pen.evaluate_chain(stale, stale, now=NOW, file_mtime=NOW - timedelta(seconds=120))
        self.assertIn("STALE_OR_MISSING_TIMESTAMP", closed["reasons"])
        duplicate = _payload()
        duplicate["live_price_diagnostics"]["collector_count"] = 2
        duplicate["live_price_diagnostics"]["duplicate_collector"] = True
        dup = pen.evaluate_chain(duplicate, duplicate, now=NOW, file_mtime=NOW)
        self.assertIn("DUPLICATE_COLLECTOR", dup["reasons"])
        self.assertFalse(dup["real_submit_allowed"])

    def test_strategy_row_must_carry_the_same_price(self):
        gateway = _payload()
        gateway["all_targets"][0]["price"] = 1
        result = pen.evaluate_chain(_payload(), gateway, now=NOW, file_mtime=NOW)
        self.assertIn("STRATEGY_PRICE_MISMATCH", result["reasons"])
        self.assertFalse(result["ok"])
