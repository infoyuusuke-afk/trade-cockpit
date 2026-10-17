# V10 main-based source admission and guarded one-click start (P0, Draft)

**Status:** GitHub synthetic-only feature. No OWNER PC changes, no runtime deployment or launch, no merge. This adds the actual startup handoff guarded by source and release-bundle admission, but current main lacks RUN/Controller/Gateway; therefore **V10 remains non-runnable from main**.

## Problem
The full V10 development stack (#435–#437) diverges substantially from current main. There is no V10 RUN/Controller/STOP in current main. Moving those scripts together would introduce many unreviewed changes. This main-based PR implements the **read-only source identity gate** and a tightly scoped entrypoint that cannot hand off to RUN until the admission succeeds and the required V10 components are in the same reviewed checkout.

## Files
- `downloads/VERIFY_V10_SOURCE_PIN_READONLY.ps1`: PowerShell 5.1 read-only Git branch/full SHA/clean worktree verifier. It has no startup, deployment, process control, network or broker entrypoint.
- `tests/test_v10_readonly_source_pin_main.py`: synthetic negative and positive fixtures on disposable GitHub Actions Windows workers.
- `downloads/START_AI_COCKPIT_V10.cmd`: canonical one-click CMD, selects only guarded V10 entry (not V8/V9/CLEAN).
- `downloads/START_AI_COCKPIT_V10.ps1`: calls the checker first, then checks 17 required V10 components and fail-closed markers in the reviewed RUN. Only then can it pass `-ApprovalFile` through to V10 RUN. `-VerifyOnly` checks all gates and exits without launch.
- `tests/test_v10_guarded_launch_main.py`: Windows temp-Git fixtures for missing pin/components, dirty/foreign source, preflight-only, and fake RUN handoff; **no real Controller/MS2/Excel is started**.
- `.github/workflows/v10-source-pin-main-readonly.yml`: Linux static contracts, Windows parser, Windows fake-RUN dynamic tests and source checker tests.
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

## Implemented guarded entry and release blockers
The canonical V10 CMD now calls `START_AI_COCKPIT_V10.ps1`, **never the old CLEAN/V9/ungated RUN**. The script always invokes `VERIFY_V10_SOURCE_PIN_READONLY.ps1` with the ignored local pin, requires an exit code 0 **and exactly one** `V10_READONLY_SOURCE=PASS`, and checks required runtime files from the same clean Git checkout. A stale V10 RUN lacking the explicit `ApprovalFile`, full-SHA, clean worktree and no-real-submit contract markers is rejected. A passed `-VerifyOnly` produces `V10_START_PREFLIGHT=PASS_NO_RUNTIME` without launching any worker. A normal start can hand off only to the same reviewed `RUN_AI_COCKPIT_V10.ps1` with the same local approval file.

**Crucial gap:** current main has no V10 RUN, Controller, Gateway, BRAIN observer or safe-stop. Thus the one-click entry deliberately refuses startup with `V10_RELEASE_COMPONENT_MISSING`. The launcher does not fetch or create those files, guess a version, or fall back to V8/V9. The existing #438 standalone safe-stop remains Draft/unmerged. Do not treat the synthetic fake-runner handoff as evidence of a deployable V10 build.

The entry does not certify Windows desktop shortcut installation, independent OWNER authorization, market-data authenticity/freshness, BRAIN port 28584 readiness, Excel coexistence, UI freshness, production process ownership or real-machine safe stop. Even after the runtime files are reviewed, each is independently blocking until Windows acceptance. The local JSON pin is **not a cryptographic approval signature**.

**Safety:** `STOP_ALLOWED=false`, `CUTOVER_ELIGIBLE=false`, `REAL_SUBMIT_ALLOWED=false`. No merge, real orders or costs are authorized.
