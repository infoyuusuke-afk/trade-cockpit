"""OWNER 2026-11-16 「決算日程タブをA＋B＋C＋Dで1つの版にして。表示と仮想の記録だけで、売買の合図・声・注文カードは付けない」.
earnings-calendar.js stays the pinned source; index.html decorates its panel."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "earnings-calendar.js").read_text(encoding="utf-8")


def _block():
    i = HTML.index("「決算日程タブをA＋B＋C＋Dで1つの版にして。")
    return HTML[i:HTML.index("</script>", i)]


class EarningsTabABCD(unittest.TestCase):
    def test_the_pinned_calendar_script_is_unchanged(self):
        self.assertNotIn("earnings_gap", JS)
        self.assertNotIn("ec-plan", JS)

    def test_a_coming_earnings_with_two_weeks_and_the_virtual_record(self):
        b = _block()
        self.assertIn('fetch("/earnings_gap.json?t="+Date.now(),{cache:"no-store"})', b)
        self.assertIn("gap=j&&j.real_submit_allowed===false&&j.trade_instruction===false?j:null", b)
        self.assertIn("16:00の記録を読めません（0件とは扱いません）。", b)
        self.assertIn('["決算日","銘柄","2週間の値動き","出来高の倍率","印"]', b)
        self.assertIn('r.candidate===true?"検証中の候補":""', b)
        self.assertIn('plan&&plan.status==="合格"?"合格":"検証中"', b)
        self.assertIn("売買の合図ではありません。声と注文カードはありません。", b)

    def test_b_past_dates_say_announced_with_the_gap(self):
        b = _block()
        self.assertIn('const p=gap&&gap.past?gap.past[code+"|"+d]:null;', b)
        self.assertIn('"発表済み・翌日の寄り "+pct(p.gap_pct)+"・寄りから "+pct(p.move_pct)', b)
        self.assertIn('lab.textContent==="未発表・期待判断の根拠不足")lab.textContent="未発表"', b)

    def test_c_momentum_lane_taken_off(self):
        b = _block()
        self.assertEqual(b.count("/^モメンタムレーン/.test("), 2)     # the status line and each stock line

    def test_d_watched_and_today_onward_by_default(self):
        b = _block()
        self.assertIn('if(!w.checked){w.checked=true;w.dispatchEvent(new Event("change"));}', b)
        self.assertIn('lab.append(box," 過ぎた日も出す")', b)
        self.assertIn("it.hidden=!day&&!showPast&&d<d0;", b)

    def test_text_only_no_signal_voice_or_order(self):
        b = "\n".join(line for line in _block().splitlines() if not line.lstrip().startswith("//"))
        self.assertNotIn("innerHTML", b)
        for word in ("cockpitSpeak", "speechSynthesis", "renderCockpitCard", "order", "#35e2ae", "#ff5a5f"):
            self.assertNotIn(word, b)


if __name__ == "__main__":
    unittest.main()
