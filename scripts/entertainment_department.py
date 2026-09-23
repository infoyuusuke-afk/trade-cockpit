"""Entertainment Department MVP: deterministic internal content planning only.

Consumes already-sanitized Cockpit events. It never publishes externally and has
no broker/order surface.
"""
from __future__ import annotations
from scripts.entertainment_pipeline import story_candidates

CHANNELS=("MANGA","X","YOUTUBE")
FORMATS={
 "MANGA":{"asset":"comic_outline","beats":4},
 "X":{"asset":"post_outline","beats":3},
 "YOUTUBE":{"asset":"video_outline","beats":5},
}

def build_editorial_queue(events,min_score=3):
    candidates=story_candidates(events,min_score)
    queue=[]
    for c in candidates:
        for channel in CHANNELS:
            spec=FORMATS[channel]
            queue.append({
              "source_event_id":c["event_id"],"channel":channel,
              "story_score":c["story_score"],"working_title":c["title_seed"],
              "asset_type":spec["asset"],"beat_count":spec["beats"],
              "status":"DRAFT_INTERNAL","owner_approval_required":True,
              "external_publish_allowed":False,
            })
    return sorted(queue,key=lambda x:(-x["story_score"],x["source_event_id"],x["channel"]))

def build_daily_brief(events,min_score=3):
    queue=build_editorial_queue(events,min_score)
    ids=[]
    for x in queue:
        if x["source_event_id"] not in ids: ids.append(x["source_event_id"])
    return {
      "department":"ENTERTAINMENT",
      "source_event_count":len(ids),"draft_count":len(queue),
      "channels":list(CHANNELS),"queue":queue,
      "status":"INTERNAL_REVIEW" if queue else "NO_CANDIDATE",
      "owner_approval_required":True,"external_publish_allowed":False,
      "research_only":True,"real_submit_allowed":False,
    }
