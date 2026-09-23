"""Translate sanitized Local Market Data Gateway state into Controller health input."""
from datetime import datetime

def adapt(snapshot, now_iso, max_age_seconds=60):
    required=("symbol","observed_at","source")
    missing=[k for k in required if not snapshot.get(k)]
    if missing:
        return result("BLOCKED","MISSING_REQUIRED",missing)
    try:
        now=datetime.fromisoformat(now_iso)
        observed=datetime.fromisoformat(snapshot["observed_at"])
        age=(now-observed).total_seconds()
    except (ValueError,TypeError):
        return result("BLOCKED","INVALID_TIMESTAMP",[])
    if age < 0:
        return result("BLOCKED","FUTURE_DATA",[])
    if age > max_age_seconds:
        return result("DEGRADED","STALE_DATA",[])
    if snapshot.get("verified") is not True:
        return result("DEGRADED","UNVERIFIED_DATA",[])
    return result("OK",None,[])

def result(state,incident,missing):
    return {"data_health":state,"incident_code":incident,"missing":missing,
            "real_submit_allowed":False,"private_data_allowed":False}
