# MS2 CSV local offline package

Download the CODE-ONLY package artifact from the successful Windows CI run
for this exact Draft PR HEAD. The package contains the launcher and allowlisted
Python sources/tests/docs only. It NEVER includes market CSVs, account files,
credentials or saved private evidence. No installer, broker call, real trade,
network request or automatic repository download is executed.

OWNER PC acceptance (not yet performed):
1. Download and extract MS2_CSV_Local_Offline.zip to a new local folder.
2. Python 3.11 or 3.12 with tkinter must already be installed.
3. Stop the MS2 Writer before accessing the intended CSV.
4. Double-click START_MS2_CSV_CAPTURE.cmd. Confirm the dialog.
5. Select exactly one existing kioxia_ticks_YYYYMMDD.csv file.
6. PASS of the 14 synthetic checks is required before market CSV read.
7. PRESERVED_UNAUTHENTICATED: LOCAL_ONLY means saved local bytes + manifest;
   BLOCKED and CANCELLED are not successful capture.

The zip is created from a fixed code allowlist, with no private data directory
included. CI extracts the ZIP separately from the checkout and runs its
synthetic acceptance to validate packaged imports. The artifact is code-only;
do not upload local evidence or the resulting captured CSVs.

The OWNER PC, actual MS2 data layout, source authentication, reparse points,
file locks and local ACL controls remain unverified after hosted CI.
source_authenticated=false, promotion_eligible=false,
real_submit_allowed=false, eligible_observed_n=0, pair_atomic=false.
No authorization for live Shadow, trading, merge or deployment.
