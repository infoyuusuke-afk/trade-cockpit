"""OWNER 2026-10-27 「GTPとGROKのアナリストの回答はおれが朝AIコクピットを起動したら、ここにコピペするやり方にして、
忘れてたら催促して…AIコクピットでも、俺に知らせるようにして（音声でも俺に知らせる）」: a banner above 注目 lists
today's missing GPT / Grok answers on weekdays 08:00-15:30 and the voice reminds every 30 minutes (at most 6 a day)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _block():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert '<div id="paste-reminder" class="paste-reminder" hidden></div><section id="attention-box"' in html
    return html.split('const KEY="cockpitPasteReminderV1";', 1)[1].split("</script>", 1)[0]


def test_checks_gpt_and_grok_for_today_on_weekdays_only():
    b = _block()
    assert "now.wd===0||now.wd===6||now.min<480||now.min>930" in b
    assert '[["pre_next","GPT PRE-NEXT"],["supply_sq","GPT 需給"]]' in b
    assert '[["Grok1号","Grok 1号"],["Grok2号","Grok 2号"],["Grok3号","Grok 3号"]]' in b
    assert "manual_analysts._arrived_today" in b


def test_banner_asks_to_paste_to_the_pc_claude_and_voice_is_rate_limited():
    b = _block()
    assert "【貼り忘れ】まだ今日の答えが届いていません：" in b and "プロジェクトのチャット（PCのClaude）に貼ってください" in b
    assert "st.count<6&&Date.now()-(st.last||0)>=30*60000&&typeof window.cockpitSpeak===\"function\"" in b
    assert "チャットのクロードに貼ってください" in b
