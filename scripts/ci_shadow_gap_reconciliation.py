"""P0-417: reconcile exactly one historic gap without claiming historic PASS.

The strict historical coverage audit remains FAIL while its one unmatched
cross-version V9 Shadow contract is not present in an archived execution.
A NEW V10 safety contract is tested independently in the same CI job.
This tool validates the gap identity and emits a separate reconciliation
status, never relabels the original coverage audit as complete.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

GAP = ("test_ai_shadow_supervisor.ContractSourceTests."
       "test_controller_and_gateway_keep_real_submit_locked")
ARCHIVE_RESULT = "P0_417_COVERAGE_RESULT=GAP_PRESENT"
V10_CONTRACT = "test_p0_417_v10_shadow_cross_version.py"


def reconcile(audit_text, audit_exit):
    found = re.findall(r"(?m)^P0_417_UNMAPPED_ID=([^\r\n]+)$", audit_text)
    mapped = re.search(r"(?m)^P0_417_COVERAGE_EXACT_MATCHED=(\d+)$", audit_text)
    archive = re.search(r"(?m)^P0_417_COVERAGE_CURRENT_ARCHIVE=(\d+)$", audit_text)
    return (audit_exit == 1 and
            ARCHIVE_RESULT in audit_text.splitlines() and
            found == [GAP] and
            mapped is not None and mapped.group(1) == "125" and
            archive is not None and archive.group(1) == "126")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("P0_417_RECONCILE=BLOCKED_WRONG_ARGUMENTS", flush=True)
        return 2
    root = Path(__file__).resolve().parents[1]
    original = [sys.executable, str(root / "scripts/ci_historic_id_coverage.py"),
                args[0], args[1]]
    observed = subprocess.run(original, cwd=str(root), text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              check=False)
    print(observed.stdout, end="", flush=True)
    if not reconcile(observed.stdout, observed.returncode):
        print("P0_417_RECONCILE=BLOCKED_UNEXPECTED_COVERAGE", flush=True)
        return 2
    path = root / "tests" / V10_CONTRACT
    if not path.is_file():
        print("P0_417_RECONCILE=BLOCKED_MISSING_V10_CONTRACT", flush=True)
        return 2
    # This test covers the current V10 implementation ONLY; never the historic V9.
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests",
           "-p", V10_CONTRACT, "-v"]
    result = subprocess.run(cmd, cwd=str(root), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            check=False)
    print(result.stdout, end="", flush=True)
    if result.returncode != 0 or not re.search(r"Ran 5 tests? in ", result.stdout):
        print("P0_417_RECONCILE=BLOCKED_V10_CONTRACT_FAIL", flush=True)
        return 2
    print("P0_417_HISTORIC_ID_COVERAGE=125_OF_126", flush=True)
    print("P0_417_UNMAPPED_V9_ID=1", flush=True)
    print("P0_417_V10_SHADOW_REPLACEMENT=5_SYNTHETIC_TESTS_PASS", flush=True)
    print("P0_417_RECONCILE=ACCOUNTED_FOR_NOT_HISTORICALLY_VERIFIED", flush=True)
    print("STOP_ALLOWED=false", flush=True)
    print("CUTOVER_ELIGIBLE=false", flush=True)
    print("REAL_SUBMIT_ALLOWED=false", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
