"""Offline broker CSV preflight, never broker authentication or reconciliation.

Only reads explicitly supplied CSV under ignored data/private/broker_exports.
No network, external provider, write, raw trade output or order path.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

MAX_BYTES=8*1024*1024
FIELDS=("execution_id","order_id","ticker","side","price","quantity","fee","executed_at","decision_snapshot_id")

def private_csv_path(repo_root,relative):
    if not isinstance(relative,str) or "\\" in relative:
        raise ValueError("PRIVATE_PATH_INVALID")
    root=Path(repo_root).resolve(strict=True)
    allowed=root/"data"/"private"/"broker_exports"
    rel=Path(relative)
    if rel.is_absolute() or ".." in rel.parts or "." in rel.parts or not rel.parts or rel.parts[:3]!=("data","private","broker_exports"):
        raise ValueError("PRIVATE_PATH_INVALID")
    target=root.joinpath(*rel.parts)
    # No symlinks / junctions in path components, even before resolve.
    current=root
    for part in rel.parts:
        current=current/part
        if current.is_symlink() or (hasattr(current,"is_junction") and current.is_junction()):
            raise ValueError("PRIVATE_PATH_LINK")
    resolved=target.resolve(strict=True)
    if not resolved.is_relative_to(allowed.resolve(strict=True)) or resolved==allowed.resolve(strict=True) or resolved.suffix.lower()!=".csv" or not resolved.is_file():
        raise ValueError("PRIVATE_PATH_INVALID")
    if resolved.stat().st_size>MAX_BYTES:
        raise ValueError("PRIVATE_FILE_TOO_LARGE")
    return resolved

def _number(value,strict_positive=False):
    try:
        v=float(value)
    except (ValueError,TypeError,OverflowError):
        return False
    return math.isfinite(v) and v>=0 and (not strict_positive or v>0)

def _timestamp(value):
    if not isinstance(value,str):
        return False
    try:
        x=datetime.fromisoformat(value.strip())
        return x.tzinfo is not None and x.utcoffset() is not None
    except (ValueError,OverflowError):
        return False

def audit_csv(path):
    """Hash raw bytes privately; report only counts/digest and reason codes."""
    # This is a process-level preflight, not a TOCTOU-immune security boundary.
    raw=path.read_bytes()
    if len(raw)>MAX_BYTES:
        raise ValueError("PRIVATE_FILE_TOO_LARGE")
    digest=hashlib.sha256(raw).hexdigest()
    errors={}
    seen=set()
    total=0
    try:
        import io
        reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig"),newline=""))
        if reader.fieldnames is None or len(reader.fieldnames)!=len(set(reader.fieldnames)) or set(reader.fieldnames)!=set(FIELDS):
            raise ValueError("CSV_COLUMN_CONTRACT_MISMATCH")
        for item in reader:
            total+=1
            reason=None
            if None in item or any(v is None for v in item.values()):
                reason="CSV_ROW_SHAPE_INVALID"
            elif any(not str(item[k]).strip() for k in ("execution_id","order_id","ticker","side","decision_snapshot_id")):
                reason="IDENTIFIER_MISSING"
            elif item["side"] not in ("BUY","SELL"):
                reason="SIDE_INVALID"
            elif not _number(item["price"],True) or not _number(item["quantity"],True) or not _number(item["fee"]):
                reason="PRICE_QTY_FEE_INVALID"
            elif not _timestamp(item["executed_at"]):
                reason="TIMESTAMP_INVALID"
            elif item["execution_id"] in seen:
                reason="DUPLICATE_EXECUTION_ID"
            if item.get("execution_id"):
                seen.add(item["execution_id"])
            if reason:
                errors[reason]=errors.get(reason,0)+1
    except (UnicodeError,csv.Error) as exc:
        raise ValueError("CSV_DECODE_OR_SYNTAX_INVALID") from exc
    return {"schema_version":"broker-offline-preflight-v1","records_examined":total,
            "rejected_records":sum(errors.values()),"eligible_to_compare":total-sum(errors.values()),
            "reasons":dict(sorted(errors.items())),"source_sha256":digest,
            "source_authenticated":False,"automated_reconciliation_allowed":False,
            "ev_training_allowed":False,"real_submit_allowed":False}

def main():
    p=argparse.ArgumentParser(description="Read-only private broker CSV shape audit")
    p.add_argument("--repo-root",default=str(Path(__file__).resolve().parents[1]))
    p.add_argument("--input",required=True,help="data/private/broker_exports/<file>.csv")
    args=p.parse_args()
    try:
        report=audit_csv(private_csv_path(args.repo_root,args.input))
    except (OSError,ValueError) as exc:
        code=str(exc) if isinstance(exc,ValueError) and str(exc).isupper() else "BROKER_CSV_READ_FAILED"
        report={"status":"BLOCKED","error":code,"source_authenticated":False,
                "automated_reconciliation_allowed":False,"ev_training_allowed":False,
                "real_submit_allowed":False}
        print(json.dumps(report,sort_keys=True))
        return 2
    print(json.dumps(report,sort_keys=True))
    return 0 if report["rejected_records"]==0 else 2

if __name__=="__main__":
    raise SystemExit(main())
