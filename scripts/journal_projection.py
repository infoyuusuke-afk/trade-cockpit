"""Project immutable events into journal rows without modifying source events."""
from __future__ import annotations
def journal_rows(events):
    out=[]
    for e in events:
        p=e.get("payload") or {}
        if e.get("domain") not in {"MARKET","STRATEGY","RISK","EXECUTION","JOURNAL","SYSTEM"}: continue
        out.append({"event_id":e["event_id"],"timestamp":e["timestamp"],"symbol":e.get("symbol"),"category":e["domain"],"event_type":e["event_type"],"summary":p.get("summary"),"decision":p.get("decision"),"result":p.get("result"),"lesson":p.get("lesson")})
    return sorted(out,key=lambda x:(x["timestamp"],x["event_id"]))
