"""OWNER 2026-10-26 「なおってない」: the KIOXIA 1-minute chart showed 項目1/項目2 boxes and no candles because
card_table_adapter.js turned the table Lightweight Charts builds inside the chart into data cards."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_adapter_skips_tables_inside_lightweight_charts():
    js = (ROOT / "card_table_adapter.js").read_text(encoding="utf-8")
    body = js.split("function convertTable(table){", 1)[1].split("}", 1)[0]
    assert 'table.closest(".tv-lightweight-charts, [data-keep-table]")' in body
    first = body.strip().splitlines()[0]
    assert first.startswith("if(") and ".tv-lightweight-charts" in first and first.endswith("return;")
