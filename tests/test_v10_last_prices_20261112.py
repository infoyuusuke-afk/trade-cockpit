"""OWNER 2026-11-12 「引け後もゲートウェイが今日の最後の値段（MS2の記録）を渡すようにして、値段がない時は合計に『含み一部なし』と書く版を作って」."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
TC = (ROOT / "trade_control.js").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
PL = (ROOT / "scripts" / "v10_positions_live.py").read_text(encoding="utf-8")


class LastPrices(unittest.TestCase):
    def test_gateway_route_is_display_only_and_today_only(self):
        i = GW.index("function Get-LastPricesView([string]$LiveJsonPath) {")
        block = GW[i:GW.index("\n}\n", i)]
        self.assertIn("if ($now.TimeOfDay -lt [TimeSpan]::new(15, 30, 0)) { return (& $fail 'BEFORE_CLOSE') }", block)
        self.assertIn("$stamp.Substring(0, 10) -cne $today) { return (& $fail 'NOT_TODAY') }", block)
        self.assertIn("$closed = [string]$live.hold_finalized_at", block)
        # audit 2026-11-12: no weekend or holiday prices (today's own trades must exist), no conflicting data
        self.assertIn("return (& $fail 'MARKET_CLOSED')", block)
        self.assertIn("'ticks.csv'", block)
        self.assertIn("return (& $fail 'NO_TRADES_TODAY')", block)
        self.assertIn("if ($live.data_conflict -eq $true) { return (& $fail 'DATA_CONFLICT') }", block)
        # audit 2026-11-12 (2nd): weekday exchange holidays by date, the same list as positions_live
        import re, sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import v10_positions_live as m
        listed = set(re.findall(r"'(\d{4}-\d{2}-\d{2})'", block[block.index("$exchangeHolidays = @("):block.index("if ($exchangeHolidays -contains $today)")]))
        self.assertEqual(listed, set(m.EXCHANGE_HOLIDAYS))
        self.assertIn("if ($exchangeHolidays -contains $today) { return (& $fail 'MARKET_CLOSED') }", block)
        self.assertIn("'HOLIDAY_LIST_EXPIRED'", block)
        self.assertIn("[string]::CompareOrdinal($hm, '09:00') -lt 0 -or [string]::CompareOrdinal($hm, '15:31') -gt 0", block)
        self.assertIn("real_submit_allowed = $false; trade_instruction = $false", block)
        self.assertIn("if ($path -eq '/last_prices.json') {", GW)
        self.assertIn("$lastView = Get-LastPricesView $liveJson", GW)

    def test_page_asks_the_gateway_only_without_todays_prices(self):
        self.assertIn('fetch("/last_prices.json?t="+Date.now(),{cache:"no-store"})', HTML)
        self.assertIn('k.schema_version==="100b-v10-last-prices-v1"&&k.real_submit_allowed===false&&k.day===today', HTML)
        self.assertIn("if(k&&k.day===today&&k.rows)window.cockpitLastPrices=k;", HTML)

    def test_missing_price_is_written_next_to_the_totals(self):
        self.assertIn("some:a.some(x=>x.yen100===null)", TC)
        self.assertIn("const miss=!!((v.dayCheck&&v.dayCheck.some)||(v.onCheck&&v.onCheck.some));", HTML)
        for part in ("(miss?'・<b class=\"vd-miss\">含み一部なし</b>':'')", "(s.open_missing>0?' <span class=\"vd-miss\">含み一部なし</span>':'')",
                     "(s.open_missing>0?'<br><small class=\"vd-miss\">含み一部なし</small>':'')", "(L.open_missing>0?' <span class=\"vd-miss\">含み一部なし</span>':'')",
                     "(groups.some(g=>g.none)?' <span class=\"vd-miss\">含み一部なし</span>':'')"):
            self.assertIn(part, HTML)
        self.assertIn('"open_missing": sum(1 for r in out if r["out"] is None and r["open_yen"] is None)', PL)
        self.assertIn('open_missing=s["rows"]["day"]["open_missing"] + s["rows"]["overnight"]["open_missing"]', PL)

    def test_size_counts_holds_without_a_price(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import v10_positions_live as m
        t = [{"in": "10:00", "out": None, "fill": 1000.0, "last": None, "side": 1, "kind": "day", "ticker": "1234", "name": "x", "rule": "r"},
             {"in": "10:05", "out": None, "fill": 1000.0, "last": 1010.0, "side": 1, "kind": "overnight", "ticker": "2345", "name": "y", "rule": "r"}]
        rows = m.size(t, 3000000, "15:40")["rows"]
        self.assertEqual(rows["day"]["open_missing"], 1)
        self.assertEqual(rows["day"]["open"], 0)          # no price is never counted as a price
        self.assertEqual(rows["overnight"]["open_missing"], 0)


if __name__ == "__main__":
    unittest.main()
