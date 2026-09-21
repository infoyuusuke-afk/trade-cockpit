#!/usr/bin/env python3
"""Point-in-time catalyst lifecycle contract. Research only."""

VALID_STATES=("SOCIAL","RUMOR","REPORTED","CONFIRMED","DENIED")

def validate_catalyst_event(event, decision_ts):
    from datetime import datetime
    state=event.get("state")
    if state not in VALID_STATES: raise ValueError("invalid catalyst state")
    if not event.get("event_id"): raise ValueError("missing event_id")
    if not event.get("observed_at"): raise ValueError("missing observed_at")
    obs=datetime.fromisoformat(str(event["observed_at"]).replace("Z","+00:00"))
    dec=datetime.fromisoformat(str(decision_ts).replace("Z","+00:00"))
    if obs>dec: raise ValueError("future catalyst information")
    return event.copy()

def catalyst_snapshot(events, decision_ts):
    """Return only knowledge available by decision time, latest state per event."""
    valid=[]
    for e in events:
        try: valid.append(validate_catalyst_event(e,decision_ts))
        except ValueError as ex:
            if str(ex)=="future catalyst information": continue
            raise
    latest={}
    for e in sorted(valid,key=lambda x:x["observed_at"]):
        latest[e["event_id"]]=e
    return list(latest.values())

def lifecycle_features(events, decision_ts):
    snap=catalyst_snapshot(events,decision_ts)
    return {
      "known_event_count":len(snap),
      "rumor_count":sum(e["state"]=="RUMOR" for e in snap),
      "reported_count":sum(e["state"]=="REPORTED" for e in snap),
      "confirmed_count":sum(e["state"]=="CONFIRMED" for e in snap),
      "denied_count":sum(e["state"]=="DENIED" for e in snap),
      "catalyst_states":"|".join(sorted({e["state"] for e in snap})) if snap else "NONE"
    }
