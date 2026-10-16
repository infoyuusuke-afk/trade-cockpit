"""Fail-closed offline receipt publisher: only source-owner supplied timestamps.

Never synthesizes last_data_at or converts process health into market evidence.
Writes only to a new private output path, never to existing source files.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from datetime import datetime,timezone
from scripts.local_source_health_contract import validate

SOURCES=frozenset(("collector","watcher","gateway","brain"))

def build_receipt(source,observed_at,last_data_at,state):
    if source not in SOURCES:
        raise ValueError("SOURCE_NOT_ALLOWED")
    if state not in ("HEALTHY","DEGRADED","STOPPED","UNKNOWN"):
        raise ValueError("INVALID_STATE")
    def parse(v):
        if not isinstance(v,str):
            raise ValueError("TIMESTAMP_NOT_SUPPLIED")
        dt=datetime.fromisoformat(v.replace("Z","+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("TIMEZONE_REQUIRED")
        return dt.astimezone(timezone.utc)
    observed=parse(observed_at)
    last=parse(last_data_at)
    if last>observed:
        raise ValueError("LAST_DATA_IN_FUTURE_RELATIVE_TO_RECEIPT")
    item={"schema_version":"local-source-health-1.0","source":source,
          "state":state,"observed_at":observed.isoformat(),
          "last_data_at":last.isoformat(),
          "consecutive_failures":0 if state=="HEALTHY" else 1,
          "reasons":[] if state=="HEALTHY" else ["SOURCE_NON_HEALTHY"]}
    if not validate(item):
        raise ValueError("RECEIPT_CONTRACT_REJECTED")
    return item

def publish_new_receipt(receipt,path):
    if not validate(receipt):
        raise ValueError("INVALID_RECEIPT")
    p=Path(path)
    if p.is_symlink() or p.exists():
        raise FileExistsError("NO_OVERWRITE_OR_SYMLINK")
    if not p.parent.is_dir() or p.parent.is_symlink():
        raise ValueError("OUTPUT_PARENT_MISSING_OR_LINK")
    payload=(json.dumps(receipt,ensure_ascii=True,sort_keys=True)+"\n").encode("ascii")
    if len(payload)>65536:
        raise ValueError("RECEIPT_TOO_LARGE")
    fd=os.open(str(p),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        try:
            p.unlink()
        except OSError:
            pass
        raise
    return p
