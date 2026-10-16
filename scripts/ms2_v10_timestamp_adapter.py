"""Explicit JST conversion for legacy V10 timestamps, never inferred silently."""
from datetime import datetime,timezone,timedelta

JST=timezone(timedelta(hours=9))
FORMAT="%Y-%m-%d %H:%M:%S"
SOURCES=frozenset(("collector","watcher","gateway","brain"))

def legacy_jst_to_utc(value,source,timezone_contract=None):
    if source not in SOURCES:
        raise ValueError("UNKNOWN_SOURCE")
    if timezone_contract!="Asia/Tokyo":
        raise ValueError("EXPLICIT_JST_CONTRACT_REQUIRED")
    if not isinstance(value,str):
        raise ValueError("TIMESTAMP_MISSING")
    parsed=datetime.strptime(value,FORMAT)
    return parsed.replace(tzinfo=JST).astimezone(timezone.utc).isoformat()

def normalize_source_timestamp(value,source,timezone_contract=None):
    if not isinstance(value,str):
        raise ValueError("TIMESTAMP_MISSING")
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:
        raise ValueError("TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        return parsed.astimezone(timezone.utc).isoformat()
    return legacy_jst_to_utc(value,source,timezone_contract)
