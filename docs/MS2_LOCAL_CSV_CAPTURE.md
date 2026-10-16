# Windows: local-only MS2 tick CSV preservation

This is an explicit one-time OWNER operation, never background capture.
It does not authenticate actual market provenance, authorize orders,
connect to MS2/Excel, or transmit any data.

Prerequisites: Python 3.11/3.12 with tkinter and repository checkout.
Stop writing to the selected CSV before using this tool.

1. Double-click scripts\run_ms2_local_csv_capture.cmd.
2. Approve the local-only dialog and select ONE existing
   kioxia_ticks_YYYYMMDD.csv file from its current folder.
3. PRESERVED_UNAUTHENTICATED: LOCAL_ONLY means its bytes were saved
   under data/private/ms2_csv_snapshots with a final manifest.
   Source-checkout mode writes to the checkout's private folder; the
   frozen Windows EXE instead uses %LOCALAPPDATA%\\AI_Cockpit_MS2_Private.
   BLOCKED and CANCELLED do not indicate a successful snapshot.

All 14 synthetic acceptance checks run first, with local private evidence.
Corrupted, moving, duplicate, symlinked or unexpected CSV inputs fail closed.
The source is never rewritten, renamed or removed. No diagnostic pair is
captured here; pair_atomic=false. The snapshot engine checks source
stability but cannot prove that the writer stopped. No automatic package
download, elevation, data upload, subscription, or broker instruction.

Fixed console codes reveal no selected path, exception text or CSV content.
Private records are Git-ignored and must NOT be uploaded to GitHub.
source_authenticated=false, promotion_eligible=false,
real_submit_allowed=false, eligible_observed_n=0 are unchanged.

The Windows GUI, owner permissions/ACL, MS2 actual file layout and live
Watcher collision are NOT verified by hosted CI. Owner-PC acceptance
is a separate step; do not claim production readiness from synthetic tests.
