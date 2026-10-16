# Windows offline synthetic acceptance

This package checks CSV preservation on the computer where it runs. It does not
connect to MS2, Excel, a broker or the network. No market-file path is accepted.
All CSVs are generated synthetic fixtures in temporary directories and removed
after testing. Existing market CSVs and running applications are not touched.

## One OWNER operation

Prerequisite: Python 3.11 or 3.12 is already available as `python`, and this PR's
checkout includes `scripts` and `tests`. No install or payment occurs at launch.
Open Command Prompt in the checkout and run:

```bat
scripts\run_ms2_offline_acceptance.cmd
```

Equivalent, including on non-Windows systems:

```text
python -m scripts.ms2_offline_acceptance
```

Do not pass CSV paths or other arguments. Exit 0 and `PASS: SYNTHETIC_ONLY` mean
all 17 checks executed without failures or skips and evidence was saved/read back.
Nonzero means BLOCKED; do not proceed to real capture. A missing Python runtime
also blocks. Symlink creation may require Windows Developer Mode. If native link creation
is unavailable, the synthetic suite exercises fail-closed link and reparse
attributes through mocked metadata instead of claiming native link coverage.
A synthetic PASS is never Windows junction/ACL acceptance. Do not elevate automatically.

## Evidence and limits

Every run saves a new JSON under `data/private/ms2_offline_acceptance/`, already
excluded by `.gitignore`. Reports contain fixed check names/statuses, UTC run time,
source-code SHA-256 hashes and false safety flags. Exceptions, skip reasons,
console text, absolute paths, usernames, CSV rows, prices and quantities are not
included. No report or CSV is automatically uploaded. CI does not upload artifacts.
Keep this directory local; never force-add private files to Git.

Checks cover byte/size/hash preservation, read-only source identity and mtime,
duplicate rejection, prior snapshot protection, malformed CSV, invalid paths,
symlinks, mid-read mutation, failed publication and corrupted readback.
The existing snapshot test suite is the executable acceptance specification.
The code hashes identify exactly which implementation and specification ran.

`real_submit_allowed=false`, `source_authenticated=false`,
`promotion_eligible=false`, `eligible_observed_n=0` always remain in evidence.
`owner_ms2_verified=false`, `real_market_capture_verified=false`, and
`pair_atomic=false` remain false even after PASS. Two-file simultaneous capture
is not guaranteed. A Windows CI PASS is synthetic runner evidence only.
Running this package on an OWNER PC proves only these synthetic checks on that
machine; real MS2 capture/authentication and production Shadow remain unverified.
Real capture is a separate acceptance step requiring an explicitly selected
offline source and private storage. This package neither starts it nor grants
permission for orders, merging or deployment.

## Poll-reset session-boundary evidence

The private snapshot manifest now includes session_audit with session row ranges, poll_seq decreases, and watcher append-clock deltas. It never edits the CSV or authenticates the source. A decrease from poll_seq 2169 to 1 becomes a restart CANDIDATE boundary; the 2026-10-16 OWNER-reported manual restart is contextual testimony, not machine proof. Adjacent recorded_at delta does not establish downtime or missing exchange ticks. Missing tick count remains null, gap_state UNKNOWN_NO_JOINED_DIAGNOSTIC, and cross_session_join_allowed false. Do not join sessions to calculate strategy PF/EV until independently verified.
