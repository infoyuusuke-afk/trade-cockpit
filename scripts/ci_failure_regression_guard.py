"""P0-417 regression fingerprint of existing FAILED monolithic CI.

Known failures are not pardoned. New failures and changed failure types are
reported; the full CI continues to return its original nonzero exit code.
"""
import json
import re
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[1] / "tests" / "ci_known_failures_p0417.json"
PATTERN = re.compile(r"(?m)^(FAIL|ERROR):\s+[^\n(]+\(([^)]+)\)\s*$")


def signatures(output):
    return sorted(set(kind + " " + test_id for kind, test_id in PATTERN.findall(output)))


def compare(output, baseline=REFERENCE):
    record = json.loads(Path(baseline).read_text(encoding="utf-8"))
    if record.get("schema") != "p0-417-known-ci-failures-v1":
        raise ValueError("unknown baseline schema")
    known = record["known_failures"]
    if known != sorted(set(known)) or not all(
        re.fullmatch(r"(FAIL|ERROR) [A-Za-z0-9_.]+", x) for x in known
    ):
        raise ValueError("invalid baseline")
    actual = signatures(output)
    new = sorted(set(actual) - set(known))
    absent = sorted(set(known) - set(actual))
    return {"known": len(known), "observed": len(actual),
            "new": new, "absent": absent,
            "regression": bool(new), "changed": bool(new or absent)}


def report(output, baseline=REFERENCE):
    try:
        data = compare(output, baseline)
    except (ValueError, OSError, KeyError, TypeError):
        print("P0_417_BASELINE_RESULT=BLOCKED_UNVERIFIED", flush=True)
        return 2
    print("P0_417_BASELINE_KNOWN=" + str(data["known"]), flush=True)
    print("P0_417_BASELINE_OBSERVED=" + str(data["observed"]), flush=True)
    print("P0_417_NEW_FAILURES=" + str(len(data["new"])), flush=True)
    print("P0_417_MISSING_KNOWN_FAILURES=" + str(len(data["absent"])), flush=True)
    for marker in data["new"]:
        print("P0_417_NEW_FAILURE_ID=" + marker, flush=True)
    print("P0_417_BASELINE_RESULT=" +
          ("REGRESSION" if data["regression"] else
           "CHANGED" if data["changed"] else "UNCHANGED"), flush=True)
    return 1 if data["regression"] else 0
