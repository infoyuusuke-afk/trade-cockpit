from datetime import datetime
from zoneinfo import ZoneInfo
from scripts.build_kioxia_dex_features import build

def ts(day, hm):
    return int(datetime.fromisoformat(f"{day}T{hm}:00").replace(tzinfo=ZoneInfo("Asia/Tokyo")).timestamp()*1000)

def test_snapshots_never_use_future_candle():
    rows=[
      {"t":str(ts("2026-09-24","08:29")),"c":"110"},
      {"t":str(ts("2026-09-24","08:31")),"c":"999"},
      {"t":str(ts("2026-09-24","08:44")),"c":"120"},
      {"t":str(ts("2026-09-24","08:56")),"c":"777"},
    ]
    x=build(rows,"2026-09-24",100)
    assert x["dex_0830"]==110
    assert x["dex_0830_gap_pct"]==10
    assert x["dex_0845"]==120
    assert x["dex_0855"]==120
