"""OWNER 2026-10-27 「オーバーナイト・スイング・バリュー銘柄を保有する場合は15時25分入ったら音声と各タブで表示してしらせること」."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _block():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert '<details id="morning-brief" class="morning-brief"></details><div id="carry-alert" class="carry-alert" hidden></div>' in html
    return html.split('const KEY="cockpitCarryAlertV1";', 1)[1].split("</script>", 1)[0]


def test_banner_from_1525_to_1545_lists_todays_overnight_decision():
    b = _block()
    assert "now.min<925||now.min>945" in b
    assert 'filter(p=>String(p.decided_at||"").slice(0,10)===now.day)' in b
    assert "15:25 持ち越し（オーバーナイト・仮想）" in b and "今日はありません" in b
    assert "スイング・バリューは、コクピットにまだ「持ち越す」判断の仕組みがありません" in b


def test_voice_once_a_day_and_unreadable_is_not_none():
    b = _block()
    assert "if(st.day!==now.day&&typeof window.cockpitSpeak===\"function\")" in b
    assert "15時25分。持ち越しは" in b
    assert "15:25 持ち越しの判断を確認できません" in b
