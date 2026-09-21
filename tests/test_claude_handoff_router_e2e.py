import unittest

from scripts.tradingview_source_router import route_tradingview_data


def claude_payload():
    return {
        "meta": {
            "symbol": "TSE:285A",
            "timeframe": "15S",
            "retrieved_at": "2026-09-21T10:00:00+09:00",
            "timezone": "Asia/Tokyo",
        },
        "bars": [
            {
                "timestamp": "2026-09-18T09:00:00+09:00",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000.0,
            }
        ],
    }


class ClaudeHandoffRouterE2ETests(unittest.TestCase):
    def test_canonical_handoff_reaches_router_as_uncrosschecked_mcp(self):
        result = route_tradingview_data(mcp_payload=claude_payload())
        self.assertEqual(result["status"], "READY_UNCROSSCHECKED")
        self.assertEqual(result["selected_source"], "TRADINGVIEW_MCP")
        self.assertFalse(result["promotion_eligible"])
        self.assertEqual(result["rows"][0]["symbol"], "TSE:285A")
        self.assertEqual(result["rows"][0]["source_timeframe"], "15S")
        self.assertEqual(result["rows"][0]["source_timezone"], "Asia/Tokyo")
        self.assertFalse(result["rows"][0]["synthetic_timeframe"])

    def test_contract_violations_become_no_usable_source(self):
        cases = (
            ("symbol", "TSE:9999", "MCP_SYMBOL_MISMATCH"),
            ("timeframe", "5", "MCP_TIMEFRAME_MISMATCH"),
            ("timezone", "UTC", "MCP_TIMEZONE_MISMATCH"),
        )
        for field, value, error in cases:
            payload = claude_payload()
            payload["meta"][field] = value
            result = route_tradingview_data(mcp_payload=payload)
            self.assertEqual(result["status"], "NO_USABLE_SOURCE")
            self.assertEqual(result["mcp_error"], error)
            self.assertEqual(result["rows"], [])
            self.assertFalse(result["promotion_eligible"])

    def test_unknown_field_and_bad_bar_never_reach_research_rows(self):
        payload = claude_payload()
        payload["meta"]["vendor"] = "unexpected"
        result = route_tradingview_data(mcp_payload=payload)
        self.assertEqual(result["status"], "NO_USABLE_SOURCE")
        self.assertTrue(result["mcp_error"].startswith("UNKNOWN_MCP_"))
        self.assertEqual(result["rows"], [])

        payload = claude_payload()
        payload["bars"][0]["volume"] = -1
        result = route_tradingview_data(mcp_payload=payload)
        self.assertEqual(result["status"], "NO_USABLE_SOURCE")
        self.assertEqual(result["mcp_error"], "INVALID_VOLUME")
        self.assertEqual(result["rows"], [])


if __name__ == "__main__":
    unittest.main()
