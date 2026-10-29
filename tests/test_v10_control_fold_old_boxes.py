"""OWNER 2026-10-27 「CONTROLタブの古い箱をたたんで。実注文OFFの1行とブレインのルール別・ブレインの選択は残して、ほかは
『詳しい状態』に入れて押した時だけ開く　あと（ひと目で）はいらない」. Display only."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _js():
    return (ROOT / "trade_control.js").read_text(encoding="utf-8")


def _html():
    return (ROOT / "index.html").read_text(encoding="utf-8")


def test_real_order_line_and_brain_rules_stay_visible():
    js = _js()
    assert 'line.id="owner-real-order-line"' in js
    assert '"実注文：OFF固定（このコクピットは注文を出しません）"' in js and '"実注文：状態を取得できません（ONとは扱いません）"' in js
    assert 'id="owner-brain-rules"' in js and 'brainBox.innerHTML=brainRuleHtml(await loadRuleShadow());' in js
    assert "<h2>成績</h2>" in js and "成績（ひと目で）" not in js


def test_old_boxes_hidden_until_detail_opened():
    js, html = _js(), _html()
    assert '<summary>詳しい状態（押すと開く）</summary>' in js
    assert 'control.classList.toggle("g-detail-open",more.open)' in js
    assert 'section.className="card wide g-old";' in js and 'section.className="card wide cc-strategy-owner-panel g-old";' in js
    assert ('.tab-pane[data-pane="control"]:not(.g-detail-open)>.cc-tab-owner-summary,'
            '.tab-pane[data-pane="control"]:not(.g-detail-open)>.g-old{display:none!important}') in html


import unittest as _unittest  # noqa: E402


class FunctionTests(_unittest.TestCase):
    """The test_ functions above, run by `python -m unittest` (CI) as well."""


for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and callable(_fn):
        setattr(FunctionTests, _name, (lambda f: lambda self: f())(_fn))
