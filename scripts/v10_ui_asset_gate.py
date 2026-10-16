"""V10 UI compatibility preflight. Read-only, no network and no deploy."""
from datetime import date, datetime
from pathlib import Path
import hashlib
import re
import sys

REQUIRED_UI = (
    "brain-runtime", "focus-cards", "cockpit-onair-cards",
    "card_system.js", "trade_control.js", "voice_client.js",
    "opportunity_radar.js", "card_table_adapter.js",
)
STAMP = re.compile(r"<header\b[^>]*>.*?\b(20\d\d-\d\d-\d\d)\b", re.I | re.S)


def inspect(raw: bytes):
    if not isinstance(raw, bytes) or not raw or len(raw) > 2_000_000:
        raise ValueError("UI_BYTES_INVALID")
    try:
        txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("UI_UTF8_INVALID") from exc
    m = STAMP.search(txt)
    if not m:
        raise ValueError("UI_DATE_UNKNOWN")
    try:
        stamp = date.fromisoformat(m.group(1))
    except ValueError as exc:
        raise ValueError("UI_DATE_INVALID") from exc
    return stamp, set(t for t in REQUIRED_UI if t in txt), hashlib.sha256(raw).hexdigest()


def audit(baseline: bytes, candidate: bytes, today: date):
    old_date, old_controls, old_sha = inspect(baseline)
    new_date, new_controls, new_sha = inspect(candidate)
    missing = sorted(set(REQUIRED_UI) - old_controls)
    incompatible = sorted(old_controls - new_controls)
    unchanged = old_sha == new_sha
    newer = old_date < new_date <= today
    allowed = not missing and not incompatible and not unchanged and newer
    return {
        "status": "PREFLIGHT_ONLY_PASS" if allowed else "BLOCKED_UI_ASSET_INCOMPATIBLE",
        "baseline_date": old_date.isoformat(),
        "candidate_date": new_date.isoformat(),
        "missing_from_baseline": missing,
        "missing_from_candidate": incompatible,
        "date_invalid": not newer,
        "identical": unchanged,
        "runtime_applied": False,
        "source_authenticated": False,
        "real_submit_allowed": False,
    }


def main(args):
    if len(args) != 2:
        print("BLOCKED_UI_ASSET_INPUTS")
        return 2
    try:
        a, b = (Path(x).resolve(strict=True) for x in args)
        if not a.is_file() or not b.is_file():
            raise ValueError("NOT_FILES")
        result = audit(a.read_bytes(), b.read_bytes(), datetime.now().date())
    except (OSError, ValueError):
        print("BLOCKED_UI_ASSET_INPUTS")
        return 2
    print(result["status"])
    print("missing_from_candidate=" + ",".join(result["missing_from_candidate"]))
    print("runtime_applied=false real_submit_allowed=false")
    return 0 if result["status"] == "PREFLIGHT_ONLY_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
