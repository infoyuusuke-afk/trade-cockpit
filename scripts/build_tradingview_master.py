#!/usr/bin/env python3
"""Build one audited TradingView 15s master from Replay CSV segments."""
import csv,json
from pathlib import Path
from scripts.tradingview_core_adapter import adapt_csv
from scripts.tradingview_stitcher import stitch_segments

FIELDS=("symbol","market_date","timestamp","open","high","low","close","volume","source","research_only")

def build_master(input_paths,symbol,output_dir):
    paths=[Path(p) for p in input_paths]
    if not paths: raise ValueError("NO_INPUT_FILES")
    segments=[adapt_csv(p,symbol) for p in paths]
    stitched=stitch_segments(segments)
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    master=out/f"{symbol}_15s_master.csv"
    audit=out/f"{symbol}_15s_master.audit.json"
    with master.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader()
        for row in stitched["rows"]: w.writerow({k:row.get(k) for k in FIELDS})
    report=dict(stitched["audit"])
    report.update({"symbol":symbol,"input_files":[p.name for p in paths],
                   "master_file":master.name,"master_rows":len(stitched["rows"]),
                   "master_usable_for_research":True,
                   "master_usable_for_live":False})
    audit.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return master,audit,report
