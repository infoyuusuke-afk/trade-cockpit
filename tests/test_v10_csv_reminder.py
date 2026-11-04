"""After-close voice reminder for the Rakuten realized P&L CSV (OWNER 2026-11-03 「引け後の作業でAIコクピットから音声出る形でしらせて」)."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CsvReminder(unittest.TestCase):
    def setUp(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.block = html.split("// OWNER 2026-11-03 「引け後の作業でAIコクピットから音声出る形でしらせて」", 1)[1].split("})();", 1)[0]

    def test_window_and_trading_day(self):
        self.assertIn("now.min<931||now.min>945", self.block)                       # 15:31-15:45
        self.assertIn("now.wd===0||now.wd===6", self.block)                          # weekdays
        self.assertIn('get("/scalp8_board.json")', self.block)                       # a holiday has no board records
        self.assertIn("x.ratio_hist.length>0", self.block)

    def test_stops_when_the_csv_arrives(self):
        self.assertIn('get("/realized_csv.json")', self.block)
        self.assertIn('rc.state==="OK"&&rc.day===now.day', self.block)
        self.assertIn("if(!st.gotSaid){st.gotSaid=true;say(", self.block)            # one line when it arrives

    def test_voice_at_most_four_times_ten_minutes_apart(self):
        self.assertIn("st.count<4&&Date.now()-(st.last||0)>=10*60000", self.block)
        self.assertIn("楽天の実現損益を、シーエスブイで、取引履歴のフォルダに保存してください", self.block)
        self.assertIn("15時45分までにお願いします", self.block)                      # the 対決 material reads it at 15:45
        self.assertNotIn("16時5分", self.block)
        for banned in ("RssOrder", "renderAttention", "real_submit"):
            self.assertNotIn(banned, self.block)


if __name__ == "__main__":
    unittest.main()
