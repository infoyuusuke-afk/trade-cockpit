"""Generate an internal storyboard from approved story candidates; never publishes."""
from __future__ import annotations
def storyboard(candidate,event_payload=None):
    p=event_payload or {}
    title=candidate.get("title_seed") or "AI Cockpit Event"
    return {"source_event_id":candidate["event_id"],"title":title,"scenes":[{"order":1,"role":"setup","text":p.get("context") or title},{"order":2,"role":"conflict","text":p.get("conflict") or "AI判断と市場変化を検証"},{"order":3,"role":"resolution","text":p.get("lesson") or "結果を記録し次の検証へ反映"}],"status":"DRAFT_INTERNAL","owner_approval_required":True,"external_publish_allowed":False}
