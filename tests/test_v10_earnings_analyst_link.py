"""OWNER 2026-10-27 「決算銘柄とアナリストをつないで。朝の指示文に今日と明日の決算銘柄を入れて全員に答えさせる、決算銘柄の欄で
GPTとGrokの判断を並べて」."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _html():
    return (ROOT / "index.html").read_text(encoding="utf-8")


def test_morning_brief_box_under_attention_lists_today_and_next_weekday_watched_earnings():
    html = _html()
    assert '<div id="paste-reminder" class="paste-reminder" hidden></div><details id="morning-brief" class="morning-brief"></details>' in html
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
