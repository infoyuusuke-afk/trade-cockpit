"""OWNER 2026-10-26 「なおってない」: the KIOXIA 1-minute chart showed 項目1/項目2 boxes and no candles because
card_table_adapter.js turned the table Lightweight Charts builds inside the chart into data cards. The adapter is a
pinned unchanged source, so index.html marks the chart's table data-keep-table right after the chart is built."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_kioxia_chart_table_is_kept_out_of_the_card_adapter():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    body = html.split("function ensureKioChart(){", 1)[1].split("kioForecastSeries=", 1)[0]
    assert "LightweightCharts.createChart(" in body
    after_create = body.split("LightweightCharts.createChart(", 1)[1]
    assert 'document.querySelectorAll("#kio-best-path table").forEach(t=>t.setAttribute("data-keep-table",""));' in after_create


def test_adapter_still_skips_tables_marked_keep():
    js = (ROOT / "card_table_adapter.js").read_text(encoding="utf-8")
    assert 'if(table.matches("[data-keep-table]"))return;' in js


def test_kioxia_boxes_use_the_same_dark_tokens_as_other_tabs():
    # OWNER 2026-10-26 「全体的に色味が他のタブとくらべて薄い」
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = html.split("全体的に色味が他のタブとくらべて薄い", 1)[1].split("</style>", 1)[0]
    assert "#kioxia-5m-calendar .kio-ms2-grid>div" in css and "background:#0E1013!important" in css
    assert "#kioxia-5m-calendar .kio-monitor-grid>div" in css and "#kioxia-5m-calendar .kio-summary>.kio-metric" in css
    assert "background:#090A0C!important" in css
    assert "#kioxia-5m-calendar .kio-metric>span" in css and "color:#9AA0AA!important" in css


def test_kioxia_chart_hides_the_1970_crosshair_date():
    # OWNER 2026-10-26 「チャート下の『01 1月 '70』も消して」: the x values are minute numbers, not dates
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    body = html.split("function ensureKioChart(){", 1)[1].split("kioForecastSeries=", 1)[0]
    assert "crosshair:{mode:LightweightCharts.CrosshairMode.Normal,vertLine:{labelVisible:false}}" in body


import unittest as _unittest  # noqa: E402


class FunctionTests(_unittest.TestCase):
    """The test_ functions above, run by `python -m unittest` (CI) as well."""


for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and callable(_fn):
        setattr(FunctionTests, _name, (lambda f: lambda self: f())(_fn))
