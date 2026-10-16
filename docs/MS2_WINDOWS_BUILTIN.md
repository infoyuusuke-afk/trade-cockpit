# MS2 offline Windows built-in mode: unsigned EXE not needed

This option uses Windows PowerShell (already present on Windows 10/11) for
a one-time, explicitly selected read-only CSV preservation. It does not
install Python or launch an unsigned EXE. It does NOT disable SmartScreen,
change ExecutionPolicy, run elevated, install packages, connect to MS2/Excel,
transmit data, or place orders.

After hosted Windows CI is SUCCESS, download the MS2_CSV_Windows_Builtin
artifact. Extract ZIP to D:\AI_Cockpit_MS2_Test. Stop the MS2 Watcher/CSV
writer. Double-click START_MS2_SAFE_CAPTURE.cmd in the extracted folder.
Approve the notice; select ONE existing kioxia_ticks_YYYYMMDD.csv.

A successful copy goes ONLY to:
D:\AI_Cockpit_Data\MS2_CSV\data\private\ms2_csv_snapshots
The source is never renamed/modified, and manifest bytes and sha256 are
verified before atomic directory publication. Source size limit is 8 MiB.
Duplicate, corrupted, linked-path, partially written, mutable CSV, unavailable
D drive or blocked script all result in BLOCKED. No automatic fallback to C:.

If Windows Security or company execution policy blocks CMD or PS1, STOP.
Do not click SmartScreen bypass controls, disable protection, or change
ExecutionPolicy; report BLOCKED instead. That remains a real acceptance issue.

Synthetic CI runs Windows PowerShell 5.1 directly from an unpacked ZIP with
only generated fake CSV. It cannot prove Owner PC policies or MS2 provenance.
source_authenticated=false; promotion_eligible=false; eligible_observed_n=0;
real_submit_allowed=false; pair_atomic=false. No real order or production
deployment is permitted.
