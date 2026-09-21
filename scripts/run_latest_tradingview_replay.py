#!/usr/bin/env python3
"""Windows-friendly one-click discovery and research runner for TradingView Replay CSV."""
import argparse,json,os,re,sys
from pathlib import Path
from scripts.run_tradingview_replay import run_replay

def downloads_dir():
    return Path(os.environ.get("USERPROFILE",Path.home()))/"Downloads"

def _candidate_score(p,symbol):
    n=p.name.lower()
    sym=symbol.lower().replace("tse:","")
    if p.suffix.lower()!=".csv" or sym not in n:return None
    # Prefer filenames that explicitly advertise seconds/15s; actual CSV is still validated downstream.
    hint=2 if re.search(r"(^|[^0-9])15\s*s([^a-z0-9]|$)",n) else (1 if "15s" in n else 0)
    return (hint,p.stat().st_mtime)

def find_latest_replay(folder=None,symbol="TSE:285A"):
    root=Path(folder) if folder else downloads_dir()
    if not root.exists():raise FileNotFoundError("DOWNLOADS_NOT_FOUND:"+str(root))
    ranked=[]
    for p in root.glob("*.csv"):
        s=_candidate_score(p,symbol)
        if s is not None:ranked.append((s,p))
    if not ranked:raise FileNotFoundError("NO_REPLAY_CSV_FOR_SYMBOL:"+symbol)
    ranked.sort(key=lambda x:x[0],reverse=True)
    return ranked[0][1]

def run_latest(folder=None,out_dir=None,symbol="TSE:285A",cost_pct=0.10,prev_close=None):
    src=find_latest_replay(folder,symbol)
    out=Path(out_dir) if out_dir else Path("data")/"replay_research_run"
    trade,ev,manifest,summary=run_replay(src,out,symbol,cost_pct,prev_close)
    return {"source_csv":str(src),"trade_results":str(trade),"ev_results":str(ev),
            "manifest":str(manifest),"bars":summary.get("bar_count"),"trades":summary.get("trade_count"),
            "research_only":True,"auto_execute":False}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--folder")
    ap.add_argument("--out-dir")
    ap.add_argument("--symbol",default="TSE:285A")
    ap.add_argument("--cost-pct",type=float,default=0.10)
    ap.add_argument("--prev-close",type=float)
    a=ap.parse_args()
    print(json.dumps(run_latest(a.folder,a.out_dir,a.symbol,a.cost_pct,a.prev_close),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
