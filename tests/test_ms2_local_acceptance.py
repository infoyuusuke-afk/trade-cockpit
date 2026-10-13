import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from scripts.ms2_local_acceptance import (
    COLLECTOR, GATEWAY, WATCHER, age_seconds, evaluate, read_only_json,
)

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 13, 9, 30, 15, tzinfo=JST)


def good():
    collector = {
        "schema_version": "ms2-common-1.0",
        "updated_at": "2026-10-13 09:30:00",
        "valid": 100,
        "universe": 100,
        "stale": False,
        "kioxia": {"price": 1000.0},
    }
    gateway = {"status": "ok", "port": 28581}
    watcher = {
        "schema_version": "kioxia-watcher-1.0",
        "updated_at": "2026-10-13 09:30:01",
        "price": 1000.0,
    }
    return collector, gateway, watcher


class MS2LocalAcceptanceTests(unittest.TestCase):
    def test_all_three_fresh_and_matching(self):
        out = evaluate(*good(), NOW)
        self.assertEqual(out["status"], "PASS")
        self.assertEqual(out["incidents"], [])
        self.assertIs(out["real_submit_allowed"], False)

    def test_missing_28582_fails(self):
        c, g, _ = good()
        self.assertIn("WATCHER_SCHEMA_OR_CONNECTION", evaluate(c, g, None, NOW)["incidents"])

    def test_gateway_wrong_identity(self):
        c, g, w = good()
        g["port"] = 28582
        self.assertIn("GATEWAY_HEALTH_OR_CONNECTION", evaluate(c, g, w, NOW)["incidents"])

    def test_collector_wrong_schema(self):
        c, g, w = good()
        c["schema_version"] = "legacy-unsafe"
        self.assertIn("COLLECTOR_SCHEMA_OR_CONNECTION", evaluate(c, g, w, NOW)["incidents"])

    def test_collector_stale(self):
        c, g, w = good()
        c["updated_at"] = "2026-10-13 09:00:00"
        self.assertIn("COLLECTOR_STALE_OR_CLOCK", evaluate(c, g, w, NOW)["incidents"])

    def test_watcher_stale(self):
        c, g, w = good()
        w["updated_at"] = "2026-10-13 09:00:00"
        self.assertIn("WATCHER_STALE_OR_CLOCK", evaluate(c, g, w, NOW)["incidents"])

    def test_price_mismatch(self):
        c, g, w = good()
        w["price"] = 1001.0
        self.assertIn("KIOXIA_PRICE_MISMATCH", evaluate(c, g, w, NOW)["incidents"])

    def test_nan_and_missing_price_fail(self):
        c, g, w = good()
        w["price"] = float("nan")
        self.assertIn("KIOXIA_PRICE_NOT_COMPARABLE", evaluate(c, g, w, NOW)["incidents"])

    def test_coverage_fails_and_blocks_trading(self):
        c, g, w = good()
        c["valid"] = 89
        out = evaluate(c, g, w, NOW)
        self.assertIn("COLLECTOR_COVERAGE_OR_STALE", out["incidents"])
        self.assertFalse(out["real_submit_allowed"])

    def test_clock_in_future_fails(self):
        c, g, w = good()
        c["updated_at"] = "2026-10-13 09:30:30"
        self.assertIn("COLLECTOR_STALE_OR_CLOCK", evaluate(c, g, w, NOW)["incidents"])

    def test_url_whitelist_prevents_outbound_or_other_endpoints(self):
        for url in ("https://example.com", "http://127.0.0.1:28583/secret",
                    "http://127.0.0.1:28580/private"):
            with self.assertRaises(ValueError):
                read_only_json(url)

    def test_no_raw_price_or_private_data_in_output(self):
        c, g, w = good()
        c["account_id"] = "secret-not-for-output"
        w["price"] = 1200
        out = evaluate(c, g, w, NOW)
        self.assertNotIn("secret-not-for-output", repr(out))
        self.assertNotIn("1200", repr(out))
        self.assertFalse(out["real_submit_allowed"])

    def test_timestamp_naive_assumed_local_jst(self):
        self.assertEqual(age_seconds("2026-10-13 09:30:00", NOW), 15)


if __name__ == "__main__":
    unittest.main()
