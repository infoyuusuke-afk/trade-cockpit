"""Read-only source health evidence from independently published JSON receipts.

This tool reads local files; it never creates a timestamp or modifies sources.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from scripts.ms2_v10_health_adapter import evaluate_v10_runtime

SOURCES=("collector","watcher","gateway","brain")
MAX_BYTES=65536

def read_json(path):
    p=Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size>MAX_BYTES:
        raise ValueError("SOURCE_FILE_UNAVAILABLE")
    with p.open("r",encoding="utf-8-sig") as f:
        data=json.load(f)
    if not isinstance(data,dict):
        raise ValueError("SOURCE_NOT_OBJECT")
    return data

def audit_files(gateway_path,source_paths,now=None):
    if set(source_paths)!=set(SOURCES):
        raise ValueError("FOUR_SOURCE_PATHS_REQUIRED")
    gateway=read_json(gateway_path)
    independent={}
    errors=[]
    for name in SOURCES:
        try:
            independent[name]=read_json(source_paths[name])
        except (OSError,ValueError,UnicodeError,json.JSONDecodeError):
            errors.append("SOURCE_RECEIPT_UNAVAILABLE_"+name.upper())
    now=now or datetime.now(timezone.utc).isoformat()
    result=evaluate_v10_runtime(gateway,independent,now)
    result["reasons"]=sorted(set(result["reasons"]+errors))
    if errors:
        result["status"]="BLOCKED"
    result["runtime_applied"]=False
    result["real_submit_allowed"]=False
    return result
