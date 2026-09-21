"""Internal entertainment/publishing preparation. External publish is always disabled."""
from __future__ import annotations

from scripts.public_event_sanitizer import validate_sanitized_event

SCORES={"TRADE_RESULT":5,"AI_DISAGREEMENT":4,"SYSTEM_INCIDENT":4,"STRATEGY_DISCOVERY":4,"DEVELOPMENT_MILESTONE":3,"DAILY_NOTE":1}


def story_candidates(events,min_score=3):
    if not isinstance(events,list):
        raise ValueError("events must be list")
    out=[]
    for e in events:
        if not validate_sanitized_event(e):
            raise ValueError("unsanitized event rejected")
        kind=e["event_type"]
        score=SCORES.get(kind,0)
        if score<min_score:
            continue
        out.append({"event_id":e["event_id"],"story_score":score,"title_seed":e["summary"],"timestamp":e["timestamp"],"external_publish_allowed":False,"owner_approval_required":True})
    return sorted(out,key=lambda x:(-x["story_score"],x["timestamp"],x["event_id"]))


def publishing_package(candidate):
    return {"source_event_id":candidate["event_id"],"title_draft":candidate["title_seed"],"status":"DRAFT_INTERNAL","owner_approval_required":True,"external_publish_allowed":False}
