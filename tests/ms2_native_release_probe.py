"""Run pre-existing native PS5.1 Bridge/Writer synthetic fixture + release gate.

All private data are disposable synthetic fixture rows. Only aggregate counts,
latency and fixed refusal codes are printed. No OWNER MS2/Excel operations.
"""
from __future__ import annotations

import json
import os
import sys

from scripts.ms2_native_release_evidence_gate import classify
from tests.ms2_concurrent_pipeline import run


def main() -> int:
    native = os.name == "nt"
    try:
        report = run(mode="normal", n=24, native=native)
    except Exception as exc:
        print(json.dumps({"status": "SYNTHETIC_RUN_FAILED",
                          "error_type": type(exc).__name__,
                          "release_eligible": False,
                          "real_submit_allowed": False}, sort_keys=True))
        return 1
    gate = classify(report)
    print(json.dumps(gate, ensure_ascii=True, sort_keys=True))
    if gate["release_eligible"] or gate["real_submit_allowed"]:
        return 1
    if native:
        # The existing native Writer must produce independently readback-verified
        # receipts; acceptance not claimed when no actual native evidence exists.
        if gate["status"] != "SYNTHETIC_EVIDENCE_CLASSIFIED_ONLY":
            return 1
        if gate["counts"]["persisted_readback"] != gate["counts"]["queued"]:
            return 1
        if gate["counts"]["queued"] is None or gate["counts"]["queued"] < 1:
            return 1
    else:
        # Linux does not emulate a Windows PowerShell 5.1 source.
        if "NATIVE_PROCESS_UNVERIFIED" not in gate["reasons"]:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
