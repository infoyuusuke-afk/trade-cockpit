"""Project verified development events into sanitized entertainment story events."""
from __future__ import annotations
import hashlib,json

ALLOWED_SKILLS={"requirements","system_design","implementation","debugging","testing","data_design","safety","documentation","ai_use","learning"}

def project_growth_event(record):
    skill=record.get("skill")
    if skill not in ALLOWED_SKILLS: raise ValueError("UNKNOWN_SKILL")
    if record.get("verified") is not True: raise ValueError("UNVERIFIED_EVENT")
    if record.get("sanitized") is not True: raise ValueError("UNSANITIZED_EVENT")
    delta=record.get("delta")
    if not isinstance(delta,int) or delta not in (-1,0,1): raise ValueError("INVALID_DELTA")
    payload={"skill":skill,"delta":delta,"event":record.get("event",""),"lesson":record.get("lesson","")}
    source_id=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return {
      "event_id":source_id,"event_type":"DEVELOPMENT_MILESTONE",
      "title":f"Developer growth: {skill}",
      "summary":payload["event"],"lesson":payload["lesson"],
      "growth":{"skill":skill,"delta":delta},
      "sanitized":True,"research_only":True,"external_publish_allowed":False,
    }
