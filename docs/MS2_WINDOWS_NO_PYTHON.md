# Python-free Windows CSV preservation build

Download the MS2_CSV_Windows_NoPython artifact from the SUCCESSFUL exact-HEAD
GitHub Actions Mobile Control Tests run. Extract the entire ZIP before use.
Double-click MS2_Local_CSV/MS2_Local_CSV.exe. No Python installation is needed.
The EXE uses a bundled Python runtime and is not digitally signed.

STOP the MS2 CSV writer first. Consent in the dialog, then select precisely
one existing kioxia_ticks_YYYYMMDD.csv. The original is never edited.
Success stores a private snapshot and manifest beside the EXE under
data/private/ms2_csv_snapshots; synthetic evidence is also stored there
under data/private/ms2_offline_acceptance. NEVER upload those local files.

Hosted Windows CI tests a fresh ZIP extraction by running the packaged EXE's
--synthetic-check option (14 synthetic checks, NO market CSV). Arbitrary
arguments are rejected. Market files are not included in the artifact.

If SmartScreen or your organization blocks unsigned applications, do NOT
disable protections to bypass the warning: report BLOCKED instead.
The OWNER PC, Tk GUI, actual MS2 CSV format, ACL and file-lock behavior
remain unverified. source_authenticated=false, promotion_eligible=false,
real_submit_allowed=false, eligible_observed_n=0, pair_atomic=false.
No broker order, deployment, merge or data transmission is authorized.
