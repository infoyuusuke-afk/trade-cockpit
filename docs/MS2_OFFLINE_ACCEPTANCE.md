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
all 14 checks executed without failures or skips and evidence was saved/read back.
Nonzero means BLOCKED; do not proceed to real capture. A missing Python runtime
also blocks. Symlink creation may require Windows Developer Mode; lack of that
capability produces BLOCKED, never a false PASS. Do not elevate automatically.

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
