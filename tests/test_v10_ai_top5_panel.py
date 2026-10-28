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
    assert "AIアナリスト注目 TOP5（当たり具合の良い順）" in b   # the title changed on 10/27 (当たり具合順); this check had not been run by unittest


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


def test_owner_follow_up_hit_rate_order_card_swap_one_line_method_and_freshness():
    """OWNER 2026-10-27 「アナリストの注目銘柄を当たり具合の良い順にTOP5…カード選択で入れ替え…一番上に今日の手法を1行…鮮度不明も直して」"""
    b = _block()
    assert "AIアナリスト注目 TOP5（当たり具合の良い順）" in b
    assert "hitScore=t=>{const r=[...(sources[t]||[])].map(x=>hitOf[x]).filter(Boolean).sort((a,b)=>b.rate-a.rate);" in b
    assert 'if(h3+m3>0)hitOf["Grok3号"]={rate:h3/(h3+m3)*100,n:h3+m3};' in b
    assert "const i=selected?st.pinned.indexOf(selected):-1;if(i>=0){st.pinned[i]=t;selected=null;" in b
    assert "今日の手法（検証中）：<b>'+esc(lab(good[0][0]))+'</b><span class=\"ai5-plain\">'+esc(plain(good[0][0]))+'</span><span class=\"ai5-num\">1回 +" in b   # OWNER 2026-10-27 「この文字変よみやすく」
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    card = html.split("window.renderScalpCard=(x,sv,tf)=>{", 1)[1].split("metrics:[", 1)[0]
    assert "Date.parse(String(x.source_timestamp_at||\"\"))" in card and "staleThresholdSeconds:120" in card


def test_list_shows_codes_and_rates_are_marked_under_verification():
    """OWNER 2026-10-27 「一覧に銘柄コードを付ける、当たり率と期待値に検証中を付ける」"""
    b = _block()
    assert 'o.textContent=code+"　"+' in b
    assert "当たり率（検証中）" in b and "期待値（検証中）" in b


def test_plain_words_for_the_gap_rules_and_claude_label():
    # OWNER 2026-10-29 「わかりにくいから寄り天・より底も追記して」; the PC Claude's rows say Claude, not GPT
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "（窓を上に開けたら寄り天を狙って空売り・下に開けたら寄り底を狙って買い）" in html
    assert 'add(x.code,/^Claude/.test(String(x.reason||""))?"Claude":' in html
    assert 'who:/^Claude/.test(String(x.reason||""))?"Claude":' in html


import unittest as _unittest  # noqa: E402


class FunctionTests(_unittest.TestCase):
    """The test_ functions above, run by `python -m unittest` (CI) as well."""


for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and callable(_fn):
        setattr(FunctionTests, _name, (lambda f: lambda self: f())(_fn))
