"""P0-417: explicit migration gate, never relabel legacy failures as PASS.

Run the original all-tests invocation (via existing attribution runner) and
accept only the exact, pinned 115 historical failures as *legacy debt*.
Any new/missing signature or inability to read the full run blocks.
This is an accounting gate, not a proof that the full suite passes.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXACT_MARKERS = {
    "P0_417_BASELINE_KNOWN=115",
    "P0_417_BASELINE_OBSERVED=115",
    "P0_417_NEW_FAILURES=0",
    "P0_417_MISSING_KNOWN_FAILURES=0",
    "P0_417_BASELINE_RESULT=UNCHANGED",
    "P0_417_ORIGINAL_EXIT_CODE=1",
    "P0_417_RESULT=FAIL",
}
def classify(output, exit_code):
    # Require the full forensic job actually executed and failed.
    lines = set(output.splitlines())
    if exit_code != 1 or not EXACT_MARKERS.issubset(lines):
        return "BLOCKED_UNEXPECTED_FAILURE"
    summary = re.search(r"(?m)^P0_417_EXECUTED=(\d+)$", output)
    if summary is None or int(summary.group(1)) < 1900:
        return "BLOCKED_INCOMPLETE_DISCOVERY"
    return "LEGACY_DEBT_UNCHANGED_NOT_FULL_PASS"

def main():
    cmd = [sys.executable, str(ROOT / "scripts/ci_attributed_unittest.py"), "--tests", "tests"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
    print(proc.stdout, end="", flush=True)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="", flush=True)
    verdict = classify(proc.stdout, proc.returncode)
    print("P0_417_MIGRATION_FORENSIC=" + verdict, flush=True)
    print("P0_417_MONOLITH_FULL_PASS=false", flush=True)
    print("REAL_SUBMIT_ALLOWED=false", flush=True)
    return 0 if verdict == "LEGACY_DEBT_UNCHANGED_NOT_FULL_PASS" else 2

if __name__ == "__main__":
    sys.exit(main())
