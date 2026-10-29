"""OWNER 2026-10-27 「GTPとGROKのアナリストの回答はおれが朝AIコクピットを起動したら、ここにコピペするやり方にして、
忘れてたら催促して…AIコクピットでも、俺に知らせるようにして（音声でも俺に知らせる）」: a banner right under 注目 lists
today's missing GPT / Grok answers on weekdays 08:00-15:30 and the voice reminds every 30 minutes (at most 6 a day)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _block():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert '<div id="attention-rows"></div></section><div id="paste-reminder" class="paste-reminder" hidden></div>' in html   # inside the 注目 wrapper (OWNER 2026-10-27 サイズ)
    return html.split('const KEY="cockpitPasteReminderV1";', 1)[1].split("</script>", 1)[0]


def test_checks_gpt_and_grok_for_today_on_weekdays_only():
    b = _block()
    assert "now.wd===0||now.wd===6||now.min<420||now.min>930" in b   # OWNER 2026-10-27: 9時前でも（7:00から）
    assert '[["pre_next","GPT PRE-NEXT"],["supply_sq","GPT 需給"]]' in b
    assert '[["Grok1号","Grok 1号"],["Grok2号","Grok 2号"],["Grok3号","Grok 3号"]]' in b
    assert "manual_analysts._arrived_today" in b


def test_banner_asks_to_paste_to_the_pc_claude_and_voice_is_rate_limited():
    b = _block()
    assert "【貼り忘れ】まだ今日の答えが届いていません：" in b and "プロジェクトのチャット（PCのClaude）に貼ってください" in b
    assert "st.count<6&&Date.now()-(st.last||0)>=30*60000&&typeof window.cockpitSpeak===\"function\"" in b
    assert "チャットのクロードに貼ってください" in b


def test_unreadable_records_say_cannot_check_and_voice_passes_the_preopen_gate():
    """OWNER 2026-10-27 「貼り忘れの音声は9時前でも鳴らして、読めない時は確認できませんと出す」"""
    b = _block()
    assert "if(!bp||!gb){" in b and "貼り忘れの確認ができません（" in b
    assert "const prevLive=window.cockpitLiveSpeechEnabled;if(prevLive===false)window.cockpitLiveSpeechEnabled=true;" in b
    assert "finally{if(prevLive===false)window.cockpitLiveSpeechEnabled=false;}" in b


import unittest as _unittest  # noqa: E402


class FunctionTests(_unittest.TestCase):
    """The test_ functions above, run by `python -m unittest` (CI) as well."""


for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and callable(_fn):
        setattr(FunctionTests, _name, (lambda f: lambda self: f())(_fn))
