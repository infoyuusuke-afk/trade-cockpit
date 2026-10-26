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
