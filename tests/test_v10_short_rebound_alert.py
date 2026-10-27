"""OWNER 2026-10-27 「ショートリバの初動を検知してほしい」: 14:00-15:00, display only, says it is not a buy signal."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _block():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert '<div id="short-rebound-alert" class="short-rebound-alert" hidden></div></div>' in html
    return html.split('const box=document.getElementById("short-rebound-alert");', 1)[1].split("</script>", 1)[0]


def test_conditions_follow_the_research_h_rule():
    b = _block()
    assert 'last.t<"14:01"||last.t>"15:00"' in b and "chg14>-1" in b
    assert 'lowBar.t<"13:30"' in b and "bars.slice(-11,-1)" in b and "Number(last.c)>hi" in b
    assert "min<840||min>930" in b


def test_live_only_display_only_and_honest_about_the_result():
    b = _block()
    assert "window.cockpitMs2ScreenReady?.(d)!==true" in b
    assert "売買の合図ではありません" in b and "PF0.35" in b
    assert "cockpitSpeak" not in b and "fetch(" not in b
