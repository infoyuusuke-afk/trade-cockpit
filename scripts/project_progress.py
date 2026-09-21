"""Deterministic daily project progress summary."""
from __future__ import annotations
def summarize(tasks):
    if not tasks:return {"overall_progress":0.0,"blocked":0,"open":0}
    total=0.0; blocked=0; open_n=0
    for t in tasks:
        p=float(t.get("progress",0))
        if p<0 or p>100: raise ValueError("progress must be 0..100")
        total+=p
        if t.get("status")=="Blocked": blocked+=1
        if t.get("status")!="完了": open_n+=1
    return {"overall_progress":round(total/len(tasks),2),"blocked":blocked,"open":open_n}
