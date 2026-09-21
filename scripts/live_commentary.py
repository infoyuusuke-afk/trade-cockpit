"""Convert internal events to safe commentary candidates; no TTS/network I/O."""
from __future__ import annotations
PRIORITY={"CRITICAL":1,"IMPORTANT":2,"NOTICE":3,"INFO":4}
def commentary_candidate(event):
    p=event.get("payload") or {}
    text=p.get("commentary_text") or p.get("summary")
    if not text:return None
    return {"event_id":event["event_id"],"priority":PRIORITY[event["severity"]],"text":str(text),"speech_text":str(p.get("speech_text") or text),"timestamp":event["timestamp"],"real_submit_allowed":False}
def select_commentary(events,limit=3):
    rows=[x for x in (commentary_candidate(e) for e in events) if x]
    rows.sort(key=lambda x:(x["priority"],x["timestamp"],x["event_id"]))
    seen=set(); out=[]
    for x in rows:
        key=x["speech_text"].strip()
        if key in seen: continue
        seen.add(key); out.append(x)
        if len(out)>=limit: break
    return out
