"""
tag_horizons.py
既存の signal_scan.py が出力する signals.json（デイ・セットアップ）を一切変更せず、
"horizon": "day" タグを付けた signals_day.json を追加生成する。

目的：デイ／スイング／長期の3階層を、後から paper_trade_history.json 等で
     横断集計できるようにするための「レイヤー分離」の第一歩。
既存の index.html / signals.json の互換性は壊さない（読み込み元は変更しない）。
"""
import json
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))


def main():
    with open("signals.json", encoding="utf-8") as f:
        src = json.load(f)

    tagged = dict(src)  # shallow copy of top-level fields
    tagged["horizon"] = "day"
    prepared = []
    for item in src.get("prepared", []):
        row = dict(item)
        row["horizon"] = "day"
        prepared.append(row)
    tagged["prepared"] = prepared
    tagged["tagged_at"] = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")

    with open("signals_day.json", "w", encoding="utf-8") as f:
        json.dump(tagged, f, ensure_ascii=False, indent=2)

    print(f"signals_day.json written: {len(prepared)} setups tagged horizon=day")


if __name__ == "__main__":
    main()
