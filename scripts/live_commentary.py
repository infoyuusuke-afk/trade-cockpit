"""Convert internal events to safe commentary candidates; no TTS/network I/O."""
from __future__ import annotations

PRIORITY={"CRITICAL":1,"IMPORTANT":2,"NOTICE":3,"INFO":4}
EXPECTED_INACTIVE_STATES={"NOT_OPEN_YET","CLOSED_KNOWN","BREAK","EXPECTED_FEED_DELAY"}
BAD_DATA_STATES={"STALE","MISSING","INVALID"}


def _session_safe_text(event, text):
    """Do not narrate an expected closed/not-open market as a data failure.

    Producers may attach session_state/data_quality either to the event
    payload or its market_context.  Expected inactivity is neutral context;
    only genuinely bad feed states may produce a data-quality warning.
    """
    p=event.get("payload") or {}
    ctx=p.get("market_context") or {}
    state=p.get("session_state") or ctx.get("session_state")
    quality=p.get("data_quality") or ctx.get("data_quality")
    if state in EXPECTED_INACTIVE_STATES and quality not in BAD_DATA_STATES:
        lowered=str(text).lower()
        bad_phrases=("未確認","unconfirmed","missing","データなし","取得不能")
        if any(x in lowered for x in bad_phrases):
            return None
    return text


def commentary_candidate(event):
    p=event.get("payload") or {}
    text=p.get("commentary_text") or p.get("summary")
    if not text:return None
    text=_session_safe_text(event,text)
    if text is None:return None
    speech=p.get("speech_text") or text
    speech=_session_safe_text(event,speech)
    if speech is None:return None
    return {"event_id":event["event_id"],"priority":PRIORITY[event["severity"]],"text":str(text),"speech_text":str(speech),"timestamp":event["timestamp"],"real_submit_allowed":False}


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
