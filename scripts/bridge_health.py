"""Bridge Health: machine-checkable sync status between the local/Cloud working
tree and origin/main, so a session never again starts implementation work from
a stale snapshot (see 2026-09-25 incident: a branch was 2150 commits behind
origin/main and STATUS.md/AI_SHARED_SHEET.md work was drafted against it).

Usage:
  python scripts/bridge_health.py                 # print current health, exit 0/1/2
  python scripts/bridge_health.py --record C-091   # record that reconciliation
                                                    # up to C-091 just happened
                                                    # at the current HEAD

Exit codes: 0 = HEALTHY, 1 = DRIFT (proceed with caution, note it), 2 = BLOCKED
(do not start implementation work; catch up with origin/main first).

No third-party dependencies; safe to run in any Python 3 environment that has
git on PATH, including a fresh Cloud session checkout.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = REPO_ROOT / "data" / "bridge_health_state.json"

# Behind-origin/main thresholds. 2150 was the real incident value; anything
# in the low hundreds is already a sign a session skipped `git fetch` for a
# while, not a healthy cadence.
DRIFT_BEHIND_THRESHOLD = 20
BLOCKED_BEHIND_THRESHOLD = 200


def _run(args):
    try:
        out = subprocess.run(
            args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30
        )
    except Exception as exc:  # pragma: no cover - defensive only
        return None, str(exc)
    if out.returncode != 0:
        return None, out.stderr.strip()
    return out.stdout.strip(), None


def _git_fetch():
    _, err = _run(["git", "fetch", "origin", "main", "--quiet"])
    return err  # None on success, else the error text (offline etc.)


def _load_state():
    if not STATE_PATH.exists():
        return {
            "last_reconciled_sha": None,
            "last_reconciled_c_id": None,
            "last_sync_timestamp": None,
        }
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def compute_health():
    fetch_err = _git_fetch()

    local_head, _ = _run(["git", "rev-parse", "HEAD"])
    origin_main, _ = _run(["git", "rev-parse", "origin/main"])

    ahead = behind = None
    if local_head and origin_main:
        counts, _ = _run(
            ["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"]
        )
        if counts:
            parts = counts.split()
            if len(parts) == 2:
                ahead, behind = int(parts[0]), int(parts[1])

    status_porcelain, _ = _run(["git", "status", "--porcelain"])
    uncommitted = len(status_porcelain.splitlines()) if status_porcelain else 0

    branch, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    upstream_counts, _ = _run(
        ["git", "rev-list", "--left-right", "--count", "@{u}...HEAD"]
    )
    unpushed = None
    if upstream_counts:
        parts = upstream_counts.split()
        if len(parts) == 2:
            unpushed = int(parts[1])

    state = _load_state()

    if fetch_err is not None:
        health = "BLOCKED"
        reason = f"git fetch origin main failed: {fetch_err}"
    elif behind is None:
        health = "BLOCKED"
        reason = "could not compute ahead/behind against origin/main"
    elif behind >= BLOCKED_BEHIND_THRESHOLD:
        health = "BLOCKED"
        reason = (
            f"{behind} commits behind origin/main (>= {BLOCKED_BEHIND_THRESHOLD}); "
            "do not start implementation work from this snapshot — create a new "
            "branch from current origin/main first"
        )
    elif behind >= DRIFT_BEHIND_THRESHOLD:
        health = "DRIFT"
        reason = f"{behind} commits behind origin/main (>= {DRIFT_BEHIND_THRESHOLD})"
    else:
        health = "HEALTHY"
        reason = f"{behind} commits behind origin/main"

    return {
        "checked_at": datetime.now(timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds"),
        "origin_main_sha": origin_main,
        "local_head_sha": local_head,
        "local_branch": branch,
        "ahead": ahead,
        "behind": behind,
        "uncommitted_changes": uncommitted,
        "unpushed_commits": unpushed,
        "last_reconciled_sha": state.get("last_reconciled_sha"),
        "last_reconciled_c_id": state.get("last_reconciled_c_id"),
        "last_sync_timestamp": state.get("last_sync_timestamp"),
        "status": health,
        "reason": reason,
    }


def print_report(report):
    print(f"Bridge Health - {report['checked_at']}")
    print(f"  status:              {report['status']}  ({report['reason']})")
    print(f"  origin/main SHA:     {report['origin_main_sha']}")
    print(
        f"  local HEAD SHA:      {report['local_head_sha']}"
        f"  (branch: {report['local_branch']})"
    )
    print(f"  ahead / behind:      {report['ahead']} / {report['behind']}")
    print(f"  uncommitted changes: {report['uncommitted_changes']}")
    print(f"  unpushed commits:    {report['unpushed_commits']}")
    print(f"  last reconciled:     {report['last_reconciled_c_id']} @ "
          f"{report['last_reconciled_sha']} ({report['last_sync_timestamp']})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        metavar="C-ID",
        help="record that a reconciliation up to this C-ID happened at the "
        "current HEAD (writes data/bridge_health_state.json)",
    )
    parser.add_argument(
        "--json", action="store_true", help="print machine-readable JSON only"
    )
    args = parser.parse_args()

    if args.record:
        local_head, _ = _run(["git", "rev-parse", "HEAD"])
        state = {
            "last_reconciled_sha": local_head,
            "last_reconciled_c_id": args.record,
            "last_sync_timestamp": datetime.now(timezone.utc)
            .astimezone()
            .isoformat(timespec="seconds"),
        }
        _save_state(state)
        print(f"Recorded reconciliation {args.record} @ {local_head}")
        return 0

    report = compute_health()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)

    return {"HEALTHY": 0, "DRIFT": 1, "BLOCKED": 2}[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
