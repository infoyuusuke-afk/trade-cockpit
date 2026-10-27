"""OWNER 2026-10-27 「このページ、今のテーマセキュリティ関連だろ、しっかり機能させろ、セキュリティ関連銘柄だして期待値銘柄のカード
タブの名称から再考」「このページいろちがう」「TDネット…と朝に気配で確認してくださいは、ききにくいそいらない」. Display and voice only."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _html():
    return (ROOT / "index.html").read_text(encoding="utf-8")


def test_tab_renamed_and_theme_cards_from_the_local_file():
    html = _html()
    assert '<button class="cockpit-tab" data-tab="pre-next">テーマ</button>' in html   # OWNER 2026-10-27 「タブ名は『テーマ』」
    assert 'intros["pre-next"]=["テーマ｜今のテーマと関連銘柄（Grok1号・毎日8:00）"' in html
    b = html.split("// OWNER 2026-10-27 「このページ、今のテーマセキュリティ関連だろ", 1)[1].split("</script>", 1)[0]
    assert 'fetch("/theme_watch.json?t="' in b and "テーマのデータを読めません" in b
    assert "期待値：コクピットの記録なし（監視100銘柄の外）" in b and "期待値ではありません" in b
    assert 'Array.isArray(v.themes)&&v.themes.length?v.themes:' in b and "Grok1号の採点（見つけた時の終値からの上げ下げ・日経比）" in b
    assert "照合NG（コードが確かめられず表示から外した）" in b


def test_gateway_serves_theme_watch_with_safe_flags_only():
    ps = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
    body = ps.split("function Get-ThemeWatchView([string]$RuntimeDir) {", 1)[1].split("\nfunction ", 1)[0]
    assert "'100b-v10-theme-watch-v1'" in body and "$view.real_submit_allowed -ne $false" in body
    assert "if ($path -eq '/theme_watch.json') {" in ps


def test_same_colours_and_shorter_ir_voice():
    html = _html()
    assert '.tab-pane[data-pane="ms2-live"] .warning,.tab-pane[data-pane="pre-next"] .warning{background:#0E1013' in html
    col = (ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
    assert "TDnet原文と翌朝の気配を確認してください" not in col
    assert '+$ir.judgement+"。")' in col


import unittest as _unittest  # noqa: E402


class FunctionTests(_unittest.TestCase):
    """The test_ functions above, run by `python -m unittest` (CI) as well."""


for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and callable(_fn):
        setattr(FunctionTests, _name, (lambda f: lambda self: f())(_fn))
