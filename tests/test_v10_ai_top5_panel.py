"""OWNER 2026-10-27 「SCL5いらない、ここをAIアナリストの注目期待値高い順TOP５をデフォルトとして、俺が任意でいれかえる形、
あと今日フォーカスする手法も表示」: in the トレード中 tab the SCALP 5 panel is hidden and an AI analyst TOP5 panel takes
its place (auto by recorded EV, OWNER swaps for the day, back to auto with a button, today's focus methods)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _block():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    return html.split('if(!pane||document.getElementById("ai-top5"))return;', 1)[1].split("</script>", 1)[0]


def test_scalp5_hidden_and_panel_in_the_trade_tab():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "const pane=document.querySelector('.tab-pane[data-pane=\"scalp\"]');" in html.split('document.getElementById("ai-top5")', 1)[0][-200:]
    b = _block()
    assert 'document.querySelectorAll(".scalp-tv").forEach(x=>{x.style.display="none";});' in b
    assert "AIアナリスト注目 TOP5（期待値順）" in b


def test_auto_order_is_ev_then_votes_and_fills_with_top_ev():
    b = _block()
    assert "evScore=t=>evOf[t]&&evOf[t][0]>=10?evOf[t][1]/evOf[t][0]:null;" in b
    assert "return votes[b]-votes[a];}).slice(0,5);" in b
    assert "期待値上位（アナリスト注目なし）" in b


def test_owner_swaps_for_the_day_and_can_go_back():
    b = _block()
    assert 'const KEY="cockpitAiTop5V1"' in b
    assert 'st={day:today(),mode:"manual",pinned:auto.slice()}' in b
    assert 'st={day:today(),mode:"auto",pinned:[]}' in b
    assert "この銘柄を外す" in b and "AIのおすすめに戻す" in b


def test_focus_methods_need_20_trades_positive_ev_and_pf():
    b = _block()
    assert "Number(v.n)>=20&&Number(v.ev_pct)>0&&Number(v.pf)>=1" in b
    assert "今日フォーカスする手法" in b and "0件とは扱いません" in b


def test_prices_only_from_fresh_rows():
    b = _block()
    assert "ok=liveOk&&row&&window.cockpitMs2RowReady?.(row)===true" in b
    assert 'failClosed:"MS2の値が新しくない・未取得"' in b
