"""Internal entertainment/publishing preparation. External publish is always disabled."""
from __future__ import annotations
SCORES={"TRADE_RESULT":5,"AI_DISAGREEMENT":4,"SYSTEM_INCIDENT":4,"STRATEGY_DISCOVERY":4,"DEVELOPMENT_MILESTONE":3,"DAILY_NOTE":1}
def story_candidates(events,min_score=3):
    out=[]
    for e in events:
        kind=e.get("event_type","")
        score=SCORES.get(kind,0)
        if score<min_score: continue
        p=e.get("payload") or {}
        out.append({"event_id":e["event_id"],"story_score":score,"title_seed":p.get("summary") or kind,"timestamp":e["timestamp"],"external_publish_allowed":False,"owner_approval_required":True})
    return sorted(out,key=lambda x:(-x["story_score"],x["timestamp"],x["event_id"]))
def publishing_package(candidate):
    return {"source_event_id":candidate["event_id"],"title_draft":candidate["title_seed"],"status":"DRAFT_INTERNAL","owner_approval_required":True,"external_publish_allowed":False}
