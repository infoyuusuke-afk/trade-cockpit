"""OWNER 2026-10-27 「解除方法はカード選択でできるようにして」: each FOCUS card can be selected by a click (blue
frame, the list follows) and has its own 解除 button; the list + 選択銘柄を解除 keep working."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _focus():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    return html.split('const key="cockpitFocusPinnedV10";', 1)[1].split('window.addEventListener("pageshow"', 1)[0]


def test_each_card_has_its_own_unpin_button():
    body = _focus()
    assert '<button type="button" class="focus-unpin" data-unpin="\'+t+\'">この銘柄を解除</button>' in body
    assert 'const un=e.target.closest("[data-unpin]");' in body
    assert "pinned=pinned.filter(x=>x!==t);" in body and "save();paint();" in body


def test_card_click_selects_and_syncs_the_list():
    body = _focus()
    assert 'const card=e.target.closest(".focus-pin");' in body
    assert "selectedCard=selectedCard===t?null:t;" in body
    assert "select.value=t;" in body
    assert 'document.getElementById("focus-owner-remove").addEventListener("click"' in body   # list way stays
