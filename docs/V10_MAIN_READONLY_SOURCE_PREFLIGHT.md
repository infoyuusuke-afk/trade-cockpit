# V10 main-based source identity preflight (P0, isolated Draft)

**Status:** GitHub synthetic-only feature. No OWNER PC changes, no runtime deployment or launch, no merge. This is a prerequisite of V10-only startup, not a runnable V10 distribution.

## Problem
The full V10 development stack (#435–#437) diverges substantially from current main. There is no V10 RUN/Controller/STOP in current main. Moving those scripts together would introduce many unreviewed changes. This small main-based PR implements only the **read-only source identity gate**.

## Files
- `downloads/VERIFY_V10_SOURCE_PIN_READONLY.ps1`: PowerShell 5.1 read-only Git branch/full SHA/clean worktree verifier. It has no startup, deployment, process control, network or broker entrypoint.
- `tests/test_v10_readonly_source_pin_main.py`: synthetic negative and positive fixtures on disposable GitHub Actions Windows workers.
- `.github/workflows/v10-source-pin-main-readonly.yml`: Linux static contracts, Windows parser and dynamic tests.
- `.gitignore`: protects the future local-only source pin from public Git.

## Future operator-only local pin
Place exactly this JSON **shape** at `downloads/V10_APPROVED_SOURCE.json` only after OWNER review and explicit approval. No pin is generated, installed or committed by this PR.

```json
{
  "schema": "v10_approved_source_v1",
  "branch": "REPLACE_WITH_INDEPENDENTLY_REVIEWED_BRANCH",
  "commit_sha": "REPLACE_WITH_EXACT_40_HEX_GIT_COMMIT",
  "real_submit_allowed": false
}
```

The fields above are placeholders, **not an authorized release**. The file is not a cryptographically signed approval, and the script prints `OWNER_AUTHENTICATED=0` even when identity checks PASS.

Only after a separate approved Windows acceptance should the owner run the read-only check from the checkout root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\downloads\VERIFY_V10_SOURCE_PIN_READONLY.ps1
```

Expected PASS markers: `V10_READONLY_SOURCE=PASS`, `GIT_BRANCH_AND_FULL_SHA_MATCH=1`, `GIT_WORKTREE_CLEAN=1`, `RUNTIME_FILES_TOUCHED=0`, `CONTROLLER_STARTED=0`, `REAL_SUBMIT_ALLOWED=0`, `OWNER_AUTHENTICATED=0`. On missing/malformed pin, detached HEAD, wrong branch/full SHA, staged/unstaged/untracked changes or git errors, it prints BLOCKED with a nonzero exit code.

No automatic `git reset`, `git clean`, `git checkout`, credentials, Excel or MS2 calls exist in the script. The Git process uses `--no-optional-locks` for index-safe inspection.

## Integration boundary
This script does not verify the installed Windows shortcut, UI freshness, MS2 market-data provenance, BRAIN 28584 readiness, full runtime file provenance or safe stop. It must be independently reviewed before another separate PR connects it to a future V10 normal startup path. Treat those issues as blocking production acceptance.

**Safety:** `STOP_ALLOWED=false`, `CUTOVER_ELIGIBLE=false`, `REAL_SUBMIT_ALLOWED=false`. No merge, real orders or costs are authorized.
