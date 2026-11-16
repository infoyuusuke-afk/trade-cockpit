"""OWNER 2026-11-16 「決算日程タブをA＋B＋C＋Dで1つの版にして。表示と仮想の記録だけで、売買の合図・声・注文カードは付けない」."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "earnings-calendar.js").read_text(encoding="utf-8")


class EarningsTabABCD(unittest.TestCase):
    def test_a_coming_earnings_with_two_weeks_and_the_virtual_record(self):
        self.assertIn("fetch('/earnings_gap.json?t='+Date.now(),{cache:'no-store'})", JS)
        self.assertIn("gap=j&&j.real_submit_allowed===false&&j.trade_instruction===false?j:null", JS)
        self.assertIn("16:00の記録を読めません（0件とは扱いません）。", JS)
        self.assertIn("['決算日','銘柄','2週間の値動き','出来高の倍率','印']", JS)
        self.assertIn("r.candidate===true?'検証中の候補':''", JS)
        self.assertIn("ok&&plan.status==='合格'?'合格':'検証中'", JS)
        self.assertIn("売買の合図ではありません。声と注文カードはありません。", JS)

    def test_b_past_dates_say_announced_with_the_gap(self):
        self.assertIn("if(x.date<todayJ){const p=gap&&gap.past?gap.past[x.code+'|'+x.date]:null;", JS)
        self.assertIn("発表済み・翌日の寄り ${pct(p.gap_pct)}・寄りから ${pct(p.move_pct)}（${p.day_n}日目まで）", JS)
        self.assertIn("x.analysis.label==='未発表・期待判断の根拠不足'?'未発表':x.analysis.label", JS)

    def test_c_no_momentum_lane(self):
        self.assertNotIn("モメンタムレーン", JS.replace("// C the momentum lane", ""))
        self.assertNotIn("x.momentum", JS)

    def test_d_watched_and_today_onward_by_default(self):
        self.assertIn('<input id="ec-watched" type="checkbox" checked> 監視銘柄のみ', JS)
        self.assertIn('<input id="ec-past" type="checkbox"> 過ぎた日も出す', JS)
        self.assertIn("const shown=events.filter(x=>selected?x.date===selected:(showPast||x.date>=todayJ));", JS)

    def test_text_only_no_signal_voice_or_order(self):
        i = JS.index("function renderPlan(){")
        block = JS[i:JS.index("fetch('earnings_calendar.json", i)]
        self.assertNotIn("innerHTML", block)              # built with textContent only
        for word in ("cockpitSpeak", "speechSynthesis", "renderCockpitCard", "order", "#35e2ae", "#ff5a5f"):
            self.assertNotIn(word, block)


if __name__ == "__main__":
    unittest.main()
