"""OWNER 2026-10-27 「決算銘柄とアナリストをつないで。朝の指示文に今日と明日の決算銘柄を入れて全員に答えさせる、決算銘柄の欄で
GPTとGrokの判断を並べて」."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _html():
    return (ROOT / "index.html").read_text(encoding="utf-8")


def test_morning_brief_box_under_attention_lists_today_and_next_weekday_watched_earnings():
    html = _html()
    # OWNER 2026-10-28 「全てのタブに同じ文言は不要…各アナリストタブ」: the box left 注目; the instructions are per analyst in the アナリスト tab
    assert 'id="morning-brief"' not in html.split("<script", 1)[0]
    assert "決算銘柄の追加指示（GPT・Grokに貼る）" in html and "mins<360||mins>690" in html   # OWNER 2026-10-27 「名前を短く」
    assert 'const fold=mins<540?"open":"fold"' in html   # OWNER 2026-10-27 「9時から後は畳む」
    assert "【朝やること】" not in html
    block = html.split("const nextWeekday=day=>", 1)[1].split("async function decorate()", 1)[0]
    assert "x.watched===true&&x.date===d" in block
    assert "GPT_ANALYST_NOTE_V1" in block and "GROK_NOTE_V2" in block
    assert "全部の銘柄について見立てを出してください" in block
    assert "先頭に「決算前」と書く" in block


def test_earnings_lines_show_gpt_and_grok_side_by_side():
    block = _html().split("async function decorate(){", 1)[1].split('document.addEventListener("DOMContentLoaded"', 1)[0]
    assert "bp.manual_analysts" in block and "bp.grok&&bp.grok.notes" in block
    assert 'who:"GPT "+(role==="supply_sq"?"需給":role==="pre_next"?"PRE-NEXT":role)' in block
    assert 'who:"Grok"' in block
    assert 'div.className="ec-ai"' in block


import unittest as _unittest  # noqa: E402


class FunctionTests(_unittest.TestCase):
    """The test_ functions above, run by `python -m unittest` (CI) as well."""


for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and callable(_fn):
        setattr(FunctionTests, _name, (lambda f: lambda self: f())(_fn))


class AnalystTab(_unittest.TestCase):
    def test_analyst_tab_after_control_with_one_instruction_per_analyst(self):
        html = _html()
        b = html.split("// OWNER 2026-10-28 「全てのタブに同じ文言は不要", 1)[1].split("</script>", 1)[0]
        self.assertIn('b.dataset.tab="analysts"', b)
        self.assertIn("const after=nav.querySelector('.cockpit-tab[data-tab=\"control\"]');", b)
        for name in ("GPT PRE-NEXT（ChatGPT）", "GPT 需給（ChatGPT）", "Grok1号 テーマ先回り（Grok）", "Grok2号 好決算監視（Grok）", "Grok3号 決算前監視（Grok）"):
            self.assertIn(name, b)
        self.assertIn('gptText("需給","需給",today,tomorrow,a,b,"需給（信用残・空売り・貸借）から見た向き","決算前・需給")', b)
        self.assertIn("決算日程を読めないので、今日の追加の指示を作れません。", b)
        self.assertNotIn("cockpitSpeak", b)
        self.assertIn("指示文は「アナリスト」タブ。", html)

    def test_cards_show_role_paste_time_last_answer_and_grok1_theme_only(self):
        # OWNER 2026-10-28 「役目・貼る時刻・その日の指示文・コピーボタン・最後の答えの時刻…Grok1号はテーマ先回りだけ」
        b = _html().split("// OWNER 2026-10-28 「全てのタブに同じ文言は不要", 1)[1].split("</script>", 1)[0]
        for label in ("<b>役目</b>", "<b>動く時刻</b>", "<b>答えを貼る時刻</b>", "<b>最後の答え</b>"):
            self.assertIn(label, b)
        self.assertIn("text:G1_TASK,g1:true}", b)
        self.assertIn("テーマ先回り・決算の追加はなし", b)
        self.assertIn("GROK_THEME_V1", b.split("const G1_TASK=", 1)[1].split("\n", 1)[0])
        self.assertEqual(b.count("paste:"), 5)
        self.assertEqual(b.count("last:lastAt("), 5)

    def test_earnings_addition_folded_as_built_into_the_tasks(self):
        # OWNER 2026-10-28 「決算の追加指示は②1回だけ入れる方式で…『定時タスクに組み込み済み』とたたむ」
        b = _html().split("// OWNER 2026-10-28 「全てのタブに同じ文言は不要", 1)[1].split("</script>", 1)[0]
        self.assertIn("(!c.g1?'<details class=\"an-fold\"><summary>定時タスクに組み込み済み（毎日貼らなくてよい）</summary>'", b)
        self.assertIn("定時タスク用_決算の追記_20261028.txt", b)
        self.assertIn('{id:"g2",cal:calPrev,', b)
        self.assertNotIn("const evening=", b)

