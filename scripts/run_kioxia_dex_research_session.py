#!/usr/bin/env python3
"""C-189 one-command research pipeline for one TSE session.

Requires already-collected DEX CSV and TSE intraday CSV. Produces/updates the
joined research dataset. Does not emit trade signals or orders.
"""
from __future__ import annotations
import argparse,csv,json,subprocess,sys,tempfile
from pathlib import Path

def run(cmd): subprocess.run([sys.executable,*cmd],check=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--dex-csv",required=True);p.add_argument("--tse-bars",required=True)
    p.add_argument("--session-day",required=True);p.add_argument("--prev-session",required=True)
    p.add_argument("--prev-close",type=float,required=True)
    p.add_argument("--dataset",default="data/research/kioxia_dex_sessions.csv")
    a=p.parse_args()
    Path(a.dataset).parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        d=Path(td)
        dex=d/"dex.csv";tse=d/"tse.json"
        run(["scripts/build_kioxia_dex_features.py","--dex-csv",a.dex_csv,"--session-day",a.session_day,
             "--prev-tse-close",str(a.prev_close),"--out",str(dex)])
        run(["scripts/build_285a_session_outcomes.py","--bars",a.tse_bars,"--prev-close",str(a.prev_close),"--out",str(tse)])
        run(["scripts/join_kioxia_dex_session.py","--dex-features",str(dex),"--tse-outcome",str(tse),
             "--prev-session",a.prev_session,"--out",a.dataset])
    print(json.dumps({"status":"ok","session_day":a.session_day,"dataset":a.dataset},ensure_ascii=False))
if __name__=="__main__":main()
