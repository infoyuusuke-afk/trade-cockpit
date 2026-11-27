"""OWNER 2026-11-17 「②画面の期待値をきびしい費用で出す版 ③8:00にMS2の値が動いていなければ声で知らせる・止める前に他のExcelが
開いていたら声で知らせる・AI注目のファイルが9:00以降に書かれたら出さない、を1つの版にする…注文はしない、合格ラインはゆるめない」."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v10_signal_ev_table as ev  # noqa: E402
import v10_trial_methods as tm  # noqa: E402

HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
STOP_RAW = (ROOT / "downloads" / "STOP_AI_COCKPIT_V10.ps1").read_bytes()
STOP = STOP_RAW.decode("ascii")


def _block(start):
    i = HTML.index(start)
    return HTML[i:HTML.index("</script>", i)]


class StrictCost(unittest.TestCase):
    def test_tick_table_is_the_coarser_standard_one(self):
        cases = {999: 1, 3000: 1, 3001: 5, 5000: 5, 5001: 10, 30000: 10, 30001: 50, 50001: 100, 300001: 500}
        for price, tick in cases.items():
            self.assertEqual(ev.tick_size(price), tick, price)

    def test_strict_cost_adds_round_trip_and_a_tick_each_way_to_the_financing(self):
        self.assertEqual(ev.STRICT_ROUND_TRIP_PCT, 0.10)
        self.assertAlmostEqual(ev.strict_cost_pct(1, 1000, 1010), 2.80 / 365 + 0.10 + 0.1 + 100 / 1010, places=9)
        self.assertAlmostEqual(ev.strict_cost_pct(-1, 4000, 4100), 1.10 / 365 + 0.10 + 5 / 4000 * 100 + 5 / 4100 * 100, places=9)
        self.assertGreater(ev.strict_cost_pct(1, 1000, 1000), ev.cost_pct(1))   # never lighter than before

    def test_every_replayed_trade_carries_the_strict_return_and_the_light_one_beside_it(self):
        r = ev._result(1, 1000, 1010, "TARGET", "09:21:00", "09:30:00")
        self.assertAlmostEqual(r["return_pct"], 1.0 - ev.strict_cost_pct(1, 1000, 1010), places=9)
        self.assertAlmostEqual(r["light_return_pct"], 1.0 - ev.cost_pct(1), places=9)
        s = ev.stats([r] * 20)
        self.assertEqual((s["cost_basis"], s["status"]), ("STRICT", "OK"))
        self.assertLess(s["ev_pct"], s["light_ev_pct"])

    def test_trial_methods_use_the_same_strict_cost(self):
        pct, yen = tm._yen(1000, 1010)
        self.assertAlmostEqual(pct, round(1.0 - 0.10 - 0.1 - 100 / 1010 - 2.8 / 365, 3), places=3)
        pct2, _ = tm._yen(1000, 1010, nights=2)
        self.assertAlmostEqual(pct - pct2, round(2 * 2.8 / 365, 3), places=3)

    def test_screen_says_strict_and_keeps_the_former_cost_only_for_comparison(self):
        self.assertIn("'<small>期待値（きびしい費用） '+(s?evPct(s.ev_pct):\"—\")+'／前の費用 '", HTML)
        self.assertIn("（検証時は前の費用で 後半", HTML)
        self.assertNotIn("期待値（費用込）", HTML)


class QuietQuotesAndOtherExcel(unittest.TestCase):
    def test_eight_oclock_check_on_trading_days_once(self):
        b = _block("「③8:00にMS2の値が動いていなければ声で知らせる")
        self.assertIn('"2026-11-23"', b)
        self.assertIn('n.wd<1||n.wd>5||HOLIDAYS.includes(n.day)||n.hms<"08:00:00"||n.hms>="08:30:00"', b)
        self.assertIn("8時を過ぎても、MS2の値が動いていません。", b)
        # audit 9e81f6f: the 28580 bridge withholds rows that are not fresh, so the gateway hashes the Collector's own file
        self.assertIn('fetch("/quote_motion.json?t="+Date.now()', b)
        self.assertIn('Number(d.rows)>0&&Number(d.file_age_sec)<=120)s=String(d.quote_hash);', b)
        self.assertNotIn("127.0.0.1:28580", b)

    def test_gateway_quote_motion_returns_only_a_hash(self):
        i = GW.index("function Get-QuoteMotionView")
        fn = GW[i:GW.index("\n}", i)]
        self.assertTrue(all(ord(ch) < 128 for ch in fn))
        self.assertIn("'100b-v10-quote-motion-v1'", fn)
        self.assertIn("[string]$x.bid + ',' + [string]$x.ask", fn)
        self.assertNotIn("$x.price", fn)
        self.assertIn("real_submit_allowed = $false; trade_instruction = $false", fn)
        self.assertIn("if ($path -eq '/quote_motion.json') {", GW)

    def test_other_excel_is_said_once_per_appearance(self):
        b = _block("「③8:00にMS2の値が動いていなければ声で知らせる")
        self.assertIn("h.runtime.other_excel_count", b)
        self.assertIn('if(Number(c)>0&&!excelOpen){excelOpen=true;keep("cockpitOtherExcelV1",{open:true});say(', b)
        # audit 9e81f6f: the page reloads every 15 minutes, so what was said survives a reload
        self.assertIn('let excelOpen=(load("cockpitOtherExcelV1")||{}).open===true;', b)
        self.assertIn('load("cockpitQuoteCheckV1")', b)
        self.assertIn('if(n.hms>="08:05:00"){quotes.spoken=true;keep("cockpitQuoteCheckV1",quotes);', b)
        self.assertIn("try{localStorage.setItem(k,JSON.stringify(v));}catch(_){}", b)
        self.assertIn("AIコクピット以外のExcelが開いています。止める前に、そのExcelを閉じてください。", b)
        code = "\n".join(line for line in b.splitlines() if not line.lstrip().startswith("//"))
        for word in ("order", "renderCockpitCard", "innerHTML", "/control"):
            self.assertNotIn(word, code)

    def test_gateway_counts_other_excel_only_when_the_v10_excel_is_known(self):
        self.assertIn("other_excel_count          = $null", GW)
        self.assertIn("if ($v10ExcelPid -gt 0) {", GW)
        self.assertIn("[int]$_.SessionId -eq $gwSession -and [int]$_.Id -ne $v10ExcelPid }).Count", GW)

    def test_safe_stop_says_the_refusal_and_still_refuses(self):
        self.assertTrue(all(c < 128 for c in STOP_RAW))
        i = STOP.index("SAFE_STOP_PREFLIGHT=BLOCKED_OTHER_EXCEL")
        block = STOP[i:STOP.index("exit 2", i) + 6]
        self.assertIn('http://127.0.0.1:28583/announce?level=CALM&text=', block)
        self.assertIn("} catch { }", block)
        say = block[block.index('$stopSay = [regex]::Unescape("') + 30:]
        say = say[:say.index('"')].encode().decode("unicode_escape")
        self.assertEqual(say, "AIコクピット以外のExcelが開いているので、止められません。そのExcelを閉じてから、もう一度止めてください。")


class AiFocusBeforeNine(unittest.TestCase):
    def test_gateway_refuses_a_lock_at_nine_or_later(self):
        i = GW.index("function Get-AiFocusView")
        fn = GW[i:GW.index("\n}", i)]
        self.assertIn("[string]::CompareOrdinal($lockedAt.Substring(11, 8), '09:00:00') -ge 0", fn)
        self.assertIn("$lockedAt.Substring(0, 10) -cne [string]$view.day", fn)
        self.assertIn("'AI_FOCUS_LOCKED_AFTER_0900'", fn)

    def test_page_hides_picks_written_at_nine_or_later(self):
        b = _block("「毎朝8:35に、コクピットの全部のアナリスト・テクニカル・板の記録・PTS・決算・Grokを使って")
        self.assertIn('lateLock=!r.ok&&!!j&&j.reason==="AI_FOCUS_LOCKED_AFTER_0900";', b)
        self.assertIn('at.slice(11,19)<"09:00:00"', b)
        self.assertIn("const picks=v.day===today&&beforeOpen&&Array.isArray(v.picks)?v.picks:[];", b)
        self.assertIn("AI注目が9:00より後に書かれたので、出しません", b)


if __name__ == "__main__":
    unittest.main()
