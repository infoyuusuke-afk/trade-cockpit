# V10 canonical one-click source pin — approval boundary

## Why this is needed
The retired historical branch `cursor/p0-stale-price-failclosed-d483` must not be silently selected for V10 startup. A checkout being present on disk is **not** permission to start it. The V10 one-click command now refuses any startup without a locally installed, explicitly reviewed **full Git branch + 40-character commit SHA**.

**Draft implementation only:** Do not install it on OWNER Windows until a separate independent review, explicit approval, rollback plan, and source-only acceptance. These checks do not validate runtime readiness or allow a broker order.

## Where the local pin lives
`downloads/V10_APPROVED_SOURCE.json` in the same directory as `START_AI_COCKPIT_V10.cmd`, ignored by Git. It must be created during a future approved installation; this project **does not generate or auto-update it** and does not commit OWNER-local data.

Example **shape only** (placeholders are deliberately invalid; NOT approved):
```json
{
  "schema": "v10_approved_source_v1",
  "branch": "REPLACE_WITH_INDEPENDENTLY_REVIEWED_V10_BRANCH",
  "commit_sha": "REPLACE_WITH_EXACT_40_HEX_COMMIT_SHA",
  "real_submit_allowed": false
}
```

The local file is a *source-selection record*, **not a cryptographic signature** or proof that an approval was granted. Do not treat it as an approval substitute or copy a Draft PR SHA into production automatically.

### Final fail-closed source admission (Draft)
- Even when the supplied branch and full SHA match, the checkout must be **clean** under `git status --porcelain=v1 --untracked-files=all`. Staged/unstaged tracked changes and untracked nonignored files are not permitted. A matching commit ID does not mean locally modified scripts are reviewed.
- A command-line `-Branch` plus `-ExpectedSha` may be used with `-VerifySourceOnly` for **read-only** source diagnostics, but can **never** authorize normal startup, `-DeployRuntimeOnly`, or `-AcceptRuntimeCollector` without an explicit `-ApprovalFile`. These are all mutating runtime modes.
- A dirty checkout is rejected with `V10_WORKTREE_NOT_CLEAN`; missing approval for a mutating mode is rejected with `V10_MUTATING_START_REQUIRES_APPROVAL_FILE` before touching runtime files or starting the Controller. **Do not automatically run git clean/reset/checkout** to hide differences. Review them and restore a verified approved checkout through a separate authorized workflow.
- The approval file is Git-ignored and may be present in the `downloads` folder without triggering the dirty-check, but this is *not* proof that the signer/author was the OWNER. Production requires independent authorization, plus machine and market-data provenance acceptance.

## Source-only preflight (future Windows acceptance, no startup)
After the review/approved pin is installed, use a read-only check instead of launching the cockpit:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\downloads\RUN_AI_COCKPIT_V10.ps1 -ApprovalFile .\downloads\V10_APPROVED_SOURCE.json -VerifySourceOnly
```

Expected result when checkout branch and full SHA match: `V10_SOURCE_ONLY=PASS`, `GIT_BRANCH_AND_FULL_SHA_MATCH=1`, `RUNTIME_FILES_TOUCHED=0`, `CONTROLLER_STARTED=0`, `REAL_SUBMIT_ALLOWED=0`, `SOURCE_AUTHENTICATED=0`. A PASS means only **Git source identity** matched. Missing file, wrong branch, short SHA, malformed manifest, disabled fail-closed gate, or `real_submit_allowed=true` must block.

Do not use `-VerifySourceOnly` with `-DeployRuntimeOnly`, `-AcceptRuntimeCollector` or `-RuntimeAcceptSelfTest`. It refuses these combinations. The git checkout is never updated as part of verification. To compare current branch/SHA without deploying, diagnostics may also use `git rev-parse --abbrev-ref HEAD` and `git rev-parse HEAD` read-only; they do **not** imply authorization.

## Actual one-click behavior
`START_AI_COCKPIT_V10.cmd` now passes the pinned local file into `RUN_AI_COCKPIT_V10.ps1`. If the file is absent, it fails closed **before runtime deployment**. A normal V10 RUN invocation with no full SHA is also rejected, even if a branch was supplied. This intentionally blocks unapproved one-click operation until a proper installation is completed.

The program still separately enforces MS2 data safety, Excel ownership, port ownership, BRAIN identity and real-submit disallow rules. No part of this document approves Windows installation, stopping V10, deployment, real trading, account access, or automatic merge.

## Release acceptance remaining
- Independent review of #434, #435, #436, #437 and order of integration; confirm no regression and pin a final immutable reviewed commit
- Demonstrate local approval file was deliberately installed without secrets in public GitHub, verify exact branch/SHA using `-VerifySourceOnly`
- Demonstrate a rollback-safe startup, single cockpit window, genuine MS2 freshness/provenance, Excel isolation, BRAIN readiness and safe stop with OWNER's explicit local authorization
- Any real order requires separate approval and independently validated order gates; currently `REAL_SUBMIT_ALLOWED=false`

**Status:** synthetic Windows/Ubuntu tests are not OWNER real-machine acceptance; `STOP_ALLOWED=false`, `CUTOVER_ELIGIBLE=false`.
