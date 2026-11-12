"""OWNER 2026-11-12 「スイング、長期銘柄もINした日付と時刻まで正確に表示、音声でもIN・OUTを知らせて」."""
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


class HoldTimes(unittest.TestCase):
    def setUp(self):
        i = HTML.index('const LKEY="cockpitHoldLiveV1";')
        self.block = HTML[i:HTML.index("function body(st,label,limit,k){", i)]

    def test_card_and_table_show_date_and_time(self):
        self.assertIn('{label:"入った日時",value:tm(o.entry_day,o.entry_time,o.entry_time_src)}', HTML)
        # no time in the record (older holds, or not in the cockpit's own trades) says so; nothing is guessed
        self.assertIn('(!t||!(src==="歩み値"||src==="引け")?"時刻の記録なし"', HTML)
        self.assertNotIn("5分足", HTML[HTML.index("const tm=(d,t,src)=>"):HTML.index("function card(o,label){")])
        self.assertIn('foot:"入り "+tm(o.entry_day,o.entry_time,o.entry_time_src)+"・"+num(o.entry)+"円。', HTML)
        self.assertIn("<th>理由</th>", HTML)
        self.assertIn("esc(tm(x.exit_day,x.exit_time,x.exit_time_src))", HTML)

    def test_live_in_out_only_with_a_fresh_price_in_the_session(self):
        b = self.block
        self.assertIn('lp&&Date.now()-lp.at<=30000&&n.wd>=1&&n.wd<=5&&n.hms>="09:00:00"&&n.hms<="15:30:00"', b)
        self.assertIn('String(q.added)<n.day&&px>=lv(q.trigger)', b)
        # a missing level never counts as reached (null -> 0 would fire at once)
        self.assertIn('const how=lv(o.stop)!==null&&px<=o.stop?"損切り":lv(o.target)!==null&&px>=o.target?"利確":null;', b)
        self.assertIn('lv(q.trigger)!==null', b)

    def test_each_event_spoken_once_and_after_the_stop_loss_voice(self):
        b = self.block
        self.assertIn("const e=Object.values(mem.ev).find(x=>!x.spoken);", b)
        self.assertIn("if(e&&!stopOn&&typeof window.cockpitSpeak===\"function\"){", b)
        self.assertIn("e.spoken=true;saveMem();", b)
        self.assertNotIn("orderCard", b)
        # 『スイング、三菱商事、8058、仮想で入りました、5,375円』: 仮想 is always said
        self.assertIn('"仮想で入りました、"+yenTxt:"仮想で出ました、"+e.how+"、"+yenTxt', b)
        for banned in ("RssOrder", "real_positions", "orderCardCopy"):
            self.assertNotIn(banned, b)


if __name__ == "__main__":
    unittest.main()
