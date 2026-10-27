"""OWNER 2026-10-27 「保有中とエントリーは明確に分けて、特にエントリータイミングがおれはみたい」:
the 注目 box shows an エントリー block (signal time with seconds, side, trigger and the virtual entry time)
and a separate 保有中（仮想） block (open rule positions and carry-overs)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _body():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    return html.split("const renderBrainToday=()=>{", 1)[1].split("const renderGrok=", 1)[0]


def test_attention_has_separate_entry_and_held_blocks():
    body = _body()
    assert "エントリー（サインの時刻・新しい順）" in body
    assert "att-sec att-sec-held\">保有中（仮想）" in body
    assert body.index("エントリー（サインの時刻・新しい順）") < body.index("att-sec-held")


def test_entry_rows_show_seconds_side_and_virtual_entry_time():
    body = _body()
    assert "x.slice(11,19)" in body and "x.slice(0,8)" in body          # HH:MM:SS
    assert "<i>'+fhm(r.captured_at)+'</i>" in body
    assert "att-side att-long\">買い" in body and "att-side att-short\">空売り" in body
    assert "エントリー待ち（発動価格に届いたら）" in body
    assert "エントリー '+fhm(p.fill_time)" in body


def test_held_block_lists_only_open_positions_and_carry_overs():
    body = _body()
    assert "rp.filter(p=>p&&p.status===\"OPEN\")" in body
    assert "持ち越し（仮想）" in body


import unittest as _unittest  # noqa: E402


class FunctionTests(_unittest.TestCase):
    """The test_ functions above, run by `python -m unittest` (CI) as well."""


for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and callable(_fn):
        setattr(FunctionTests, _name, (lambda f: lambda self: f())(_fn))
