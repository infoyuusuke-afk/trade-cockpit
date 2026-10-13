"""Read-only Japanese broker CSV HEADER recognition, without reading trade rows.

An offline candidate for private user-selected files. Known header names
are illustrative, *not a verified Rakuten CSV contract*. No account data,
trade data, prices or file contents are printed or uploaded.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

try:
    from .private_broker_csv_preflight import private_csv_path, MAX_BYTES
except ImportError:
    from private_broker_csv_preflight import private_csv_path, MAX_BYTES

JP_HEADER_CANDIDATES={
    "約定日","受渡日","銘柄コード","銘柄名","売買区分","数量［株］",
    "単価［円］","手数料［円］","税金等［円］","諸費用［円］",
}
JP_CRITICAL={"約定日","銘柄コード","売買区分","数量［株］","単価［円］"}
ENCODINGS=("utf-8-sig","cp932")

def inspect_header(path: Path):
    data=Path(path).read_bytes()
    if len(data)>MAX_BYTES:
        raise ValueError("PRIVATE_FILE_TOO_LARGE")
    fingerprint=hashlib.sha256(data).hexdigest()
    detected=None
    for encoding in ENCODINGS:
        try:
            decoded=data.decode(encoding)
        except UnicodeDecodeError:
            continue
        try:
            reader=csv.reader(io.StringIO(decoded,newline=""))
            header=next(reader,None)
        except (csv.Error,StopIteration):
            header=None
        if header is not None:
            detected=(encoding,header)
            break
    if detected is None:
        return {"status":"BLOCKED","reason":"ENCODING_OR_HEADER_UNREADABLE",
                "source_sha256":fingerprint,"source_authenticated":False,
                "reconciliation_allowed":False,"ev_training_allowed":False}
    encoding,header=detected
    names=[x.strip() for x in header]
    matching=set(names)&JP_HEADER_CANDIDATES
    required_missing=JP_CRITICAL-set(names)
    # Only aggregate counts + known public schema names, never the actual
    # unknown header values (which can contain private content).
    return {"schema_version":"broker-jp-header-candidate-v1",
            "status":"JP_HEADER_CANDIDATE_ONLY" if not required_missing and len(names)==len(set(names)) else "BLOCKED",
            "encoding_candidate":encoding,"columns_count":len(names),
            "recognized_column_count":len(matching),
            "missing_known_fields":sorted(required_missing),
            "duplicate_header_count":len(names)-len(set(names)),
            "source_sha256":fingerprint,
            "source_authenticated":False,
            "reconciliation_allowed":False,
            "ev_training_allowed":False,
            "real_submit_allowed":False}

def main():
    p=argparse.ArgumentParser(description="Offline candidate Japanese broker header preflight")
    p.add_argument("--repo-root",default=str(Path(__file__).resolve().parents[1]))
    p.add_argument("--input",required=True)
    args=p.parse_args()
    try:
        result=inspect_header(private_csv_path(args.repo_root,args.input))
    except (OSError,ValueError) as exc:
        result={"status":"BLOCKED","reason":"PRIVATE_CSV_INVALID",
                "source_authenticated":False,"reconciliation_allowed":False,
                "ev_training_allowed":False,"real_submit_allowed":False}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result["status"]=="JP_HEADER_CANDIDATE_ONLY" else 2

if __name__=="__main__":
    raise SystemExit(main())
