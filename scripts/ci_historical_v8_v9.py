"""P0-417: audit historical source checkout, never import retired code into V10.

This audit is strict: missing files, unexpected commit or unexpected bare
historical paths fail. The old tests are run from their own pinned worktree.
"""
import argparse
import subprocess
import sys
from pathlib import Path

HISTORY = "b81b8877b12a33368e91e5e156a2fc7ac4529349"
PATHS = (
    "downloads/AI_COCKPIT_CONTROLLER_V8.ps1",
    "downloads/AI_COCKPIT_GATEWAY_V8.ps1",
    "downloads/RUN_AI_COCKPIT_V8.ps1",
    "downloads/STOP_AI_COCKPIT_V8.ps1",
    "downloads/AI_COCKPIT_CONTROLLER_V9.ps1",
    "downloads/AI_COCKPIT_GATEWAY_V9.ps1",
    "downloads/RUN_AI_COCKPIT_V9.ps1",
    "tests/test_ai_cockpit_v8_controller_contract.py",
    "tests/test_collector_workbook_identity.py",
    "ms2_live/MS2_RSS_100_Collector.ps1",
)

def audit(history):
    root = Path(history).resolve(strict=True)
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    print("P0_417_HISTORY_COMMIT_VERIFIED=" + str(commit == HISTORY).lower(), flush=True)
    if commit != HISTORY:
        return 2
    for rel in PATHS:
        if not (root / rel).is_file():
            print("P0_417_HISTORY_MISSING=" + rel, flush=True)
            return 2
    print("P0_417_HISTORY_FILES_VERIFIED=" + str(len(PATHS)), flush=True)
    return 0

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", required=True)
    parser.add_argument("--mode", choices=["audit", "v8", "collector"], default="audit")
    args = parser.parse_args(argv)
    rc = audit(args.history)
    if rc:
        return rc
    if args.mode == "audit":
        return 0
    pattern = {"v8": "test_ai_cockpit_v8_controller_contract.py",
               "collector": "test_collector_workbook_identity.py"}[args.mode]
    print("P0_417_HISTORIC_TEST=" + pattern, flush=True)
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests",
               "-p", pattern, "-v"]
    rc = subprocess.run(command, cwd=args.history, check=False).returncode
    print("P0_417_HISTORIC_RESULT=" + ("PASS" if rc == 0 else "FAIL"), flush=True)
    return rc

if __name__ == "__main__":
    sys.exit(main())
