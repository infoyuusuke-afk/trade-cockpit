# P0 V10 independent BRAIN safe stop and branch-pinned read-only preflight

P0-14 fixes a real independent BRAIN cleanup omission: the owner-facing V10 safe-stop script did not include brain_observer_pid even though the Controller created that child in P0-13. Safe Stop now checks its exact recorded PID and Python script identity before attempting to terminate it. No general python.exe or Excel name matching is allowed.

New script: downloads/AI_COCKPIT_V10_BRAIN_PREFLIGHT.ps1. It only reads Git branch and full pinned SHA, Git tracked file cleanliness, the STOP script BRAIN registration, local V10 Controller state, the private BRAIN status file, and 127.0.0.1:28581/health. It never installs, launches or kills workers, modifies any local or git file, reads broker account data, or sends private rows outside the machine.

Usage is for a later separately authorized OWNER-PC deployment, not now. Example after a reviewed branch/SHA is actually installed:

powershell.exe -NoProfile -File "C:\AI_Cockpit_Current\trade-cockpit\downloads\AI_COCKPIT_V10_BRAIN_PREFLIGHT.ps1" -RepoRoot "C:\AI_Cockpit_Current\trade-cockpit" -ExpectedBranch "APPROVED_BRANCH" -ExpectedSha "FULL_40_CHARACTER_APPROVED_SHA"

No approved install branch or full SHA for OWNER PC has been authorized in this step. DO NOT run this against active market Excel until integration and rollback are separately approved.

Results: BLOCKED exit 2 with nonsensitive blocker codes, or OBSERVATION_ONLY exit 0 when fresh and owned BRAIN process status confirms an independent observer. Never establishes authenticated exchange ticks, strategy expectancy, safe trade execution, profitability, or cross-source join. Real submit remains prohibited. Windows CI checks source syntax, synthetic bad timestamp/false authentication/wrong SHA, and wrong-SHA refusal against an ephemeral Git checkout. None of these are actual OWNER Windows/MS2 live acceptance. No PRs were merged and no PC deployment or rollback was performed.

## P0-14 Windows synthetic *real process* stopping evidence (not OWNER PC)

Dedicated Windows + Ubuntu workflow: https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/38945853919

Windows hosted runner executes the **real** `downloads/STOP_AI_COCKPIT_V10.ps1` against disposable, current-run synthetic Controller and Python child processes and a private RUNNER_TEMP state folder. The CI test never starts the real BRAIN script; Python runs only a sleep loop with observer-looking arguments. The test does not access MS2, the OWNER PC, any Excel workbook, any market feed, broker interface or account data. Additional unrelated Python remains alive throughout. Cleanup is bounded even if a test fails.

All six process tests PASS on Windows (10.155 s): owned Controller+BRAIN exit and state removal; foreign PID refusal with state retention; missing observer PID refusal; malformed JSON refusal; foreign Controller PID refusal; already-exited BRAIN is idempotent. The existing six source tests also PASS on Windows and Ubuntu; Windows PS5.1 parse + synthetic preflight + bad-SHA refusal PASS. These test results provide stronger CI evidence but **do not** constitute a live Windows/OWNER acceptance or prove that Stop always works with actual MS2, business Excel, Collector, Watcher, network permissions or arbitrary process-termination failures.

The broad Mobile Control Tests workflow remains FAIL for the current HEAD, and is not certified by this dedicated PASS. Its failures must be independently triaged, rather than silently changing P0-14 scope to the old V9 test suite.

## Remaining stop/deployment acceptance gate

- Keep PR #403 in Draft, no automatic merge and no real orders.
- Review the PR stack relative to its parent #402; pin the full SHA and branch for a separately approved installation only after integration, safety and rollback review.
- Preserve the current installed files and Controller-state evidence before changing any OWNER machine runtime.
- Establish safe restoration to the previous known-good startup/stop installation and independent BRAIN teardown; do not invoke a new Safe Stop version against unmatched old Controller state.
- An authorized on-machine, nontrading acceptance must verify the actual recorded Controller/BRAIN identity and fresh state, then confirm the managed processes exit and unrelated Excel/Python/Collector/Watcher instances are not targeted.
- A nonzero refusal, stale identity, or retained state means STOP is **not** verified and requires investigation, not an unconditional retry or an unrelated-process kill.

## P0-15 Desktop stop launcher route and rollback audit

### Observed repository facts (not a verified OWNER machine installation)

- Parent Draft PR #402 head is the base commit of Draft PR #403: 6fe2574b0ac2b95cc384b05eb5afbb538f1c99ac.
- The tracked downloads/STOP_AI_COCKPIT_V10.cmd invokes its sibling STOP_AI_COCKPIT_V10.ps1. However, the actual desktop "AIコクピット_安全停止.cmd" is outside GitHub, and its *current* bytes/target cannot be confirmed remotely.
- downloads/RUN_AI_COCKPIT_V10.ps1 has an older default Branch (cursor/p0-stale-price-failclosed-d483). Merely fetching PR #403 does **not** select or install it. No automatic branch switch is allowed for this acceptance.
- Legacy downloads/STOP_AI_COCKPIT.ps1 enumerates process command-lines, and legacy INSTALL_AI_COCKPIT_CLEAN_STARTUP.ps1 can install that broad STOP script. Do not invoke/replace the OWNER's stop entry with those legacy files.
- The runtime-only V10 RUN script has a Collector file backup/restore mechanism; this is **not** proof of full versioned rollback of Desktop launchers, Controller, Gateway, BRAIN and Safe Stop together.

### Separate read-only Desktop route verification

New script: downloads/VERIFY_V10_DESKTOP_SAFE_STOP_ROUTE.ps1. It requires an *explicit* actual Desktop CMD path, a local repository path, and approved full 40-hex Git SHA + branch. It reads (does not execute) CMD text, rejects multiple shell operations, extra commands, missing/unresolved target, legacy STOP, dirty tracked checkout, SHA/branch mismatch and a Safe Stop that lacks the BRAIN contract. It returns only VERIFIED_READONLY/exit 0 or BLOCKED/exit 2. Success never establishes that an old process is safely stopped or that the machine is installed/approved.

Only **after** branch/SHA approval and after the matching code is deliberately installed, an operator can run this read-only check with appropriate values:

    powershell.exe -NoProfile -File "C:\AI_Cockpit_Current\trade-cockpit\downloads\VERIFY_V10_DESKTOP_SAFE_STOP_ROUTE.ps1" -RepoRoot "C:\AI_Cockpit_Current\trade-cockpit" -DesktopStopCmd "THE_ACTUAL_DESKTOP_STOP_CMD_FULL_PATH" -ExpectedBranch "APPROVED_BRANCH" -ExpectedSha "APPROVED_FULL_40_HEX_SHA"

Do not substitute the repo CMD path for the actual Desktop CMD when checking what the OWNER normally clicks. The tracked repository wrapper has its own isolated CI contract test only.

### Required installation and rollback safety gate (not yet executed)

1. Confirm the working active Desktop START/STOP entry targets, local Git full SHA/branch, installed runtime version, state-file location, and actual running-process identities. Capture only non-sensitive local diagnostics; do not upload private state or market snapshots.
2. Create immutable local backups of the entire pair of Desktop entry files and V10 RUN/STOP/Controller/Gateway/BRAIN files **before** any replacement; record paths and SHA256 values. The in-repo Collector runtime backup does not substitute for this checkpoint.
3. Refuse the deployment if a tracked V10 Controller/BRAIN PID or any relevant worker cannot be safely attributed to the intended repo/runtime; do not replace the active Safe Stop entry or rely on a generic process killer.
4. Independently verify the exact new Desktop safe stop CMD target + approved Git HEAD with the *read-only* route audit. Fail-closed/BLOCKED means no deployment.
5. In separately authorized nontrading Windows acceptance, stop all specifically owned worker processes and confirm unrelated work Excel, Python, Collector, Watcher and other processes are not terminated. Retain state when actual stop is incomplete.
6. Only after every worker is confirmed stopped may the previously backed-up launchers and code be restored together. Revalidate the restored stop route **before** any restart. Do not assume an older STOP script can terminate a newer independent BRAIN safely.
7. If a stop, restore or identity check fails, leave the system in HOLD and retain local evidence. Do not silently report SAFE or enable live submission. No unattended Owner machine deployment has been authorized.

The CI Desktop-route fixture runs inside GitHub-hosted Windows and uses a disposable synthetic Git repo; **it never inspects or executes the real Desktop launcher**.

## P0-16 Owner desktop start/stop read-only inventory (implementation, not deployed)

New downloads/INVENTORY_V10_OWNER_DESKTOP_READONLY.ps1 reads the local checkout branch/full SHA and tracked-file cleanliness, checks the concrete V10 RUN and STOP source files, and classifies the **actual Desktop** CMD pair by matching explicit PowerShell -File invocation targets. Only these two names are considered: AIコクピット_起動.cmd and AIコクピット_安全停止.cmd. It never executes the CMD contents; no scripts, Excel automation, process control, network requests, logs, CSV reads, uploads or file writes occur. It emits classification codes only; no Windows paths, PIDs, branch names, account data, command-line text or market observations are printed.

After separate, explicit approval of the exact installed branch and complete commit SHA, the read-only inspection command on an OWNER machine is:

    powershell.exe -NoProfile -File "C:\AI_Cockpit_Current\trade-cockpit\downloads\INVENTORY_V10_OWNER_DESKTOP_READONLY.ps1" -RepoRoot "C:\AI_Cockpit_Current\trade-cockpit" -ExpectedBranch "APPROVED_BRANCH" -ExpectedSha "APPROVED_FULL_40_HEX_SHA"

If the Desktop is in a separate known folder, specify -DesktopRoot "ACTUAL_DESKTOP_FOLDER". Do not assume GitHub changes are already installed locally, and do not run the example against an old installation. An absent CMD, a different/legacy target, a missing V10 source, a bad pin or a dirty tracked checkout returns BLOCKED / exit 2. A successful ROUTES_READONLY_VERIFIED / exit 0 is **not** proof of active V10 running state, actual shutdown behavior or rollback readiness. In particular, Windows .lnk shortcut destinations, multiple Desktop folders and running-process ownership are not verified by this scanner; treat those separately before any adoption.

GitHub-hosted isolated Windows fixture (11 acceptance cases, synthetic Desktop and synthetic pinned Git checkout) tests normal route, old startup/stop, missing files, arbitrary commands, dirty checkout, wrong pin and absence of the target folder. This does not provide any OWNER PC evidence.


## P0-17 Windows shortcut (.lnk) target verification

The **same read-only** downloads/INVENTORY_V10_OWNER_DESKTOP_READONLY.ps1 script now supports an additional explicit `-VerifyShortcuts` switch, which requires two recognized Desktop shortcuts as well as the previously checked CMD start/stop pair. It reads .lnk targets and arguments using the Unicode IShellLinkW interface and IPersistFile.Load in STGM_READ mode; no ShellLink Resolve or Save is called, no shortcut or CMD is executed, and only coarse classifications are emitted. GitHub's Windows fixtures create temporary .lnk files with WScript.Shell and Unicode-aware renaming, but the production auditor does not use WScript.Shell. It inspects Desktop .lnk files with names beginning with AI Cockpit or AIコクピット, recognizes START/STOP or 起動/安全停止, and blocks duplicate roles and unclassified AI shortcuts. Valid targets must directly point to the fully SHA/branch-pinned repository `downloads/START_AI_COCKPIT_V10.cmd` and `downloads/STOP_AI_COCKPIT_V10.cmd`, with empty Arguments and an empty or approved downloads WorkingDirectory. Both tracked CMD wrappers must match the exact vetted source contract. Any .lnk that instead targets powershell.exe, cmd.exe, old V9 launchers, another Python script, a CMD on an unapproved Desktop, or contains extra arguments is BLOCKED until independently reviewed; we do not rewrite shortcuts in the audit.

The scan remains limited to the specified DesktopRoot. Windows may have a public Desktop, OneDrive Desktop, and per-user Desktop; those other locations are **not verified by a single invocation**. An absent, unsupported, or conflicting shortcut must not be silently treated as no risk. Only after the approved matching source is actually installed and a separate change-control decision is recorded, the optional read-only check may be used:

    powershell.exe -NoProfile -File "C:\AI_Cockpit_Current\trade-cockpit\downloads\INVENTORY_V10_OWNER_DESKTOP_READONLY.ps1" -RepoRoot "C:\AI_Cockpit_Current\trade-cockpit" -ExpectedBranch "APPROVED_BRANCH" -ExpectedSha "APPROVED_FULL_SHA" -VerifyShortcuts

Successful output `ROUTES_AND_SHORTCUTS_READONLY_VERIFIED` establishes only that the inspected Desktop's routes resolve to the pinned local source; it does **not** establish live MS2 collection, safe stop on OWNER PC, installed Controller/BRAIN parity, rollback, or trading authorization. This new check is exercised only with synthetic Windows GitHub Actions shortcuts in disposable RUNNER_TEMP directories. The actual OWNER PC shortcuts have not been read or changed.


## P0-19 Verified local backup checkpoint before cutover

Following the first OWNER read-only diagnostic, the actual PC checkout was found on the older `cursor/p0-stale-price-failclosed-d483` branch (not PR #403), and the visible `AI Cockpit START.lnk` invokes `cmd.exe` -> `C:\AI_Cockpit_OneClick_Starter\AI_COCKPIT_START_DEBUG.cmd` -> `START_AI_COCKPIT.ps1`, which in turn refers to old Collector/Gateway/Heartbeat helpers rather than the V10 RUN/Controller scripts. This is real local evidence for a stale alternate startup path, **not** proof that V9 or a current BRAIN instance is running.

New `downloads/PREPARE_V10_SAFE_CUTOVER_V1.ps1` offers only:

- `-Mode Plan` (default): **no writes**, reports candidate file counts and whether installed Git branch + full SHA match a supplied intended pin. It does not run a shutdown, launch the app, switch Git branches, or change any CMD/.lnk.
- `-Mode BackupOnly`: Creates a **new, local-only snapshot** underneath `StateRoot\V10_cutover_snapshots` by default (never a GitHub upload). Selectively backs up the old Starter, DEBUG CMD, the existing RUN/STOP/Controller/Gateway entry code, and AI-prefixed .cmd/.lnk entries from explicit or discovered Desktop locations. It refuses missing essential launchers, fewer than two Desktop CMDs, missing Desktop shortcut, oversized/non-regular files, reparse points for checked paths, invalid SHA format and an unsafe destination within the Git checkout or Desktop. It verifies source/copy SHA-256 pairs, then writes a local JSON manifest of relative file names, sizes, hashes and `real_submit_allowed=false`. An incomplete backup is a blocker, not a PASS.
- The current older checkout is **expected to differ** from the intended future pin. This does not prevent backing up that old installation, but the manifest records `source_pin_match=false`. That is not an authorization to start the old or the new build.
- No restore/cutover/apply mode exists: a verified backup is a **prerequisite**, not the completed rollback or live acceptance. Broker credentials, market CSVs and arbitrary workbook files are intentionally excluded; personal local scripts remain private on the OWNER device.

**Windows synthetic CI:** `tests/test_v10_safe_cutover_prepare.py` uses GitHub-hosted disposable Windows directories and an isolated fake Git repo, including a legacy DEBUG CMD, two desktop CMDs, one LNK, files to exclude, and synthetic V10 code. All 10 cutover tests PASS on Windows, including no-change Plan, byte-for-byte backup integrity, old branch mismatch allowed for backup, missing-entry refusal and no CSV/credential inclusion. Dedicated Windows/Ubuntu CI: https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/38953524686 .

**No installation or user PC backup has been executed yet.** The script currently exists only in the Draft PR; it is not present in the owner's old local checkout. Obtain an approved, exact-commit-pinned and integrity-checked delivery of this script before considering any PC backup run. On-machine rollout must separately authorize the correct staged branch, offline rollback mechanics, PIN-matched clean code, and read-only cross-desktop .lnk/CMD acceptance before changing any active launcher. Do not run the old broad STOP script as a shortcut.


## P0-19B Owner real-machine backup discovery I/O failure and correction

OWNER's actual Windows PowerShell run of the earlier pinned Plan showed `BLOCK_STAGE=DISCOVER_CANDIDATES`, `BLOCK_REASON=IO_FAILURE`, `CUTOVER_PLAN=BLOCKED`, `DIAG_EXIT=2`. This is evidence of an I/O failure **during discovery** but does not identify which Desktop folder or establish a successful snapshot. The old scanner enumerated **every** regular Desktop file before filtering by AI-prefixed .cmd/.lnk, which can inspect irrelevant cloud-synced entries. Do not infer a specific file/OneDrive culprit without further evidence.

The corrected `Get-Candidates` performs only filtered per-folder `AI*.cmd` and `AI*.lnk` enumeration, without broad `Get-ChildItem` of unrelated files. A selected Desktop that still fails discovery remains fail-closed. `BLOCK_DESKTOP_INDEX` (ordinal, no absolute paths) and `BLOCK_DISCOVERY_ACTION` (fixed vocabulary such as `ENUM_AI_CMD`, `ENUM_AI_LNK`, `DESKTOP_ATTRIBUTES`) identify the failed operation while suppressing exception content. GitHub Windows Actions uses disposable Desktop fixtures and verifies unrelated files/CSV are excluded; all 14 backup-related synthetic checks pass at code HEAD `6d386e18fd7578516f0b734a2360bae50e59684e` in https://github.com/infoyuusuke-afk/trade-cockpit/actions/runs/38955377351 .

**Next owner action only after published SHA-pinned integrity check:** run the corrected `-Mode Plan` *once*, not `-Mode BackupOnly`, and report output classifications. If it still reports BLOCKED, do not re-run BackupOnly or change shortcut/Git; use the ordinal/action result to narrow the inaccessible Desktop location. No OWNER PC files have been changed by GitHub commits; the prior failed local backup must not be counted as completed.


## P0-19D Optional Desktop quarantine — incomplete inventory must never permit cutover

OWNER's real-machine Plan diagnostic returned `BLOCK_STAGE=DISCOVER_CANDIDATES`, `BLOCK_REASON=IO_FAILURE`, `BLOCK_DESKTOP_INDEX=3`, and `BLOCK_DISCOVERY_ACTION=DESKTOP_ATTRIBUTES`. Thus the I/O failure occurred when retrieving attributes of the third Desktop candidate. The actual folder identity and contents have **not** been verified. The existing primary Desktop pair (two CMDs) and another Desktop's START shortcut (one LNK) were observed separately; the third is not conclusively empty.

The preparer now quarantines a whole missing/inaccessible/reparse Desktop while still collecting entry files from other accessible roots. The quarantine is visible as `UNVERIFIED_DESKTOP_COUNT`, `UNVERIFIED_DESKTOP_INDEX`, and `UNVERIFIED_DESKTOP_ACTION`, not silently skipped. These outputs disclose only an ordinal and a fixed operation class, never paths, names, file contents or exception text. Critical root/Repo/Starter checks and per-file errors outside optional Desktop enumeration remain fail-closed.

In **Plan**, any quarantined Desktop produces `CUTOVER_PLAN=READ_ONLY_PARTIAL` and `CUTOVER_ELIGIBLE=false`; Plan never writes. In **BackupOnly**, the known accessible entry files can be hashed and copied locally; successful verification produces `BACKUP_RESULT=VERIFIED_PARTIAL_LOCAL_ONLY` rather than the complete-backup success code. The local manifest records `desktop_inventory_complete=false`, the unverified Desktop indexes/actions, and `cutover_eligible=false`. This is **partial evidence only**, not a full recovery point or authorization to install, change a desktop link, stop processes, merge, or trade. Investigate the missing Desktop separately before an actual V10 cutover.

Windows synthetic regression tests cover both a missing optional Desktop and a third Desktop represented by an NTFS junction/reparse point without following it, while requiring SHA-256-verified backup integrity for accessible files. No OWNER machine paths or runtime files have been accessed by these CI tests.

## P0-20 Snapshot restore rehearsal — isolated only; OWNER has a partial receipt

The OWNER's actual local partial backup contains 11 files, with zero SHA-256 mismatches and an independent BACKUP_RECEIPT=PASS_PARTIAL. It is not a complete Desktop snapshot: the third Desktop folder failed at DESKTOP_ATTRIBUTES. The separately tried Windows account is an unverified hypothesis for that folder, and the OWNER rejected that operating model; do not restore a separate-account Excel workflow.

New `downloads/VERIFY_V10_SNAPSHOT_RESTORE_REHEARSAL.ps1` accepts an explicitly supplied local snapshot directory and validates the v10_cutover_backup_v1 manifest, safety flags (cutover and real trading disabled), exact allowed relative path shape, file sizes and SHA-256, mandatory historical entrypoints, duplicate names, and symlink/reparse source paths. No private paths, account records, workbook data or files are uploaded.

- `-Mode VerifyOnly` checks every backed-up file but never copies or writes; successful receipt is SNAPSHOT_RECEIPT=VERIFY_PASS. A manifest that reports an incomplete Desktop inventory produces SNAPSHOT_INVENTORY=PARTIAL.
- `-Mode Rehearse` verifies the whole source snapshot, then copies each file to a **new temporary directory under OS TEMP**; it rejects external staging paths and reparse-point/junction ancestors. All staged bytes receive a second SHA-256 comparison. Successful result is SNAPSHOT_RECEIPT=REHEARSAL_PASS, meaning isolated copy only, **not** active restoration.
- Neither mode can modify real Desktop CMD/LNK, Starter, Controller, BRAIN, MS2 or work Excel. CUTOVER_ELIGIBLE=false, REAL_SUBMIT_ALLOWED=false remain mandatory; neither mode stops processes or merges/deploys a PR.
- Real rollback still needs a separately verified destination mapping for actual original Desktop locations, which the old manifest does not contain (desktop1/desktop2 are ordinals, not absolute recovery paths), as well as safe stop, immutable version pin, operator review, and authorization.

The Windows synthetic test suite creates fake snapshots under disposable TEMP only and covers corrupt bytes, unsupported source names, traversal, tampered manifest, missing required entrypoints, unsafe staging destination, and NTFS source/staging junction refusal. No OWNER PC rollback or production restore has occurred. Broad Mobile Control Tests are separate from dedicated P0 CI.


## P0-21 Recovery destination discovery without trusting Desktop ordinals

The Owner's 11-entry partial snapshot has an independently checked SHA-256 receipt (0 mismatches), but its v1 manifest lists Desktop entries by ordinal (`desktop1`, `desktop2`). Those old ordinals are **not** proof of original absolute paths, and a discarded separate-Windows-account experiment must **not** be reinstated or silently searched as part of recovery.

New `downloads/VERIFY_V10_RESTORE_TARGET_MAP.ps1` is read-only. It first invokes the P0-20 verified snapshot checker, then compares the exact filename, byte count and SHA-256 of the archived entry with candidate current local starter/repo files or AI-prefixed `.cmd`/`.lnk` entries in **explicitly supplied, authorized DesktopRoots**. It never uses the old `desktopN` number for matching. If two folders contain identical candidate bytes, the match is ambiguous and is not resolved. If the historical source changed or disappeared, the match is missing. Inaccessible or reparse Desktop roots are quarantined and counted, never treated as empty.

The only output is aggregate matching evidence: counts of verified/missing/ambiguous entries, Desktop entry counts, unverified Desktop root ordinals, and `TARGET_MAP_STATUS`. Neither paths nor raw shortcut contents are exported or written to a new manifest. `TARGET_MAP_STATUS=PARTIAL_HOLD` is required whenever an archived Desktop remains unverified, any entry cannot be matched uniquely, or a supplied Desktop root is inaccessible. Even if all candidates match and the snapshot claims complete inventory, `TARGET_MAP_STATUS=READONLY_MATCH_ONLY` is **not** authorization to perform a restore or production cutover; `CUTOVER_ELIGIBLE=false` and `REAL_SUBMIT_ALLOWED=false` are unconditional.

A future production rollback requires a separate **local-only** absolute destination map, its independent verification, a completed rather than partial Desktop inventory, an approved version pin, safe isolation of actual processes and an authorized nontrading cutover window. None of these has been completed merely by source matching. The legacy START shortcut still points to a DEBUG CMD, and the local Git branch is old. Do not replace them based on this synthetic CI.

The new Windows-only tests use fake local snapshots and allow-listed Desktop fixture folders: they specifically reverse Desktop ordinals, check identical byte collisions in two candidate folders, stale/modified sources, missing shortcuts, an inaccessible third candidate, tampered snapshots, invalid trade flags, duplicate Desktop roots, and Japanese filenames, without contacting the OWNER PC.

## P0-22 Private encrypted destination evidence (Windows DPAPI, no restoration)

The Owner's historical backup is PARTIAL (11 files, previously independently verified); third Desktop is UNVERIFIED. Desktop ordinals from the snapshot are never treated as authoritative destination paths. The rejected separate-Windows-account Excel experiment is not reintroduced.

`downloads/VERIFY_V10_RESTORE_TARGET_MAP.ps1` retains its default read-only behavior, with an **optional** `-SaveEncryptedMap` switch. Only that explicit switch creates a local evidence record at `StateRoot/V10_private_restore_maps/<random-id>.dpapi`. It collects exact SHA-256 and size-matching original targets in a volatile process, then encrypts the full private absolute path list using Windows DPAPI **CurrentUser**, bound to the Windows account SID, Starter root, checkout root, originating snapshot manifest hash, and explicit allowed Desktop roots. It returns only an opaque map ID plus summary codes. It never outputs raw absolute paths, target command arguments, broker data, or plaintext JSON to chat/GitHub.

Separate `downloads/VERIFY_V10_ENCRYPTED_RESTORE_MAP.ps1` loads the map by a validated 32-hex identifier, decrypts locally under the **same Windows user context**, revalidates its account and root binding, independently rechecks the snapshot and original manifest, and recomputes stored target SHA-256 against the live local files. It reports only aggregate matched/stale counts and `ENCRYPTED_MAP_RECEIPT=VERIFIED_PARTIAL_HOLD`, `STALE_HOLD`, or `BLOCKED`. Even a fully verified encrypted map is **not** a production restore, completeness guarantee, authorization for cutover or a substitute for the missing Desktop#3 evidence: `CUTOVER_ELIGIBLE=false` and `REAL_SUBMIT_ALLOWED=false` are unconditional.

DPAPI CurrentUser protects confidentiality of stored target paths from another ordinary Windows account; it is not a substitute for a secured Windows user session, disk protections, or account compromise defenses. A different account cannot normally decrypt the record, but cross-account denial is not proven by single-account CI. Loss of the user profile's DPAPI keys can make the evidence unreadable; the underlying independently verified snapshot remains separate. The encrypted evidence file alone does not contain an automatically executable rollback or destination overwrite procedure.

GitHub-hosted Windows-only synthetic acceptance checks use disposable local folders and fake snapshots to test default no-write scanning, encrypted write and independent re-verification, ciphertext tampering refusal, stale target detection, changed manifest refusal, invalid map identifiers and duplicate destination ambiguity. **The OWNER PC has not executed or installed this new capability**, and no local private map has yet been created on that machine. P0-22 completion is code and synthetic CI evidence only.

## P0-23 Pinned, bounded one-operation delivery (no live deployment)

The latest Draft PR adds `downloads/RUN_V10_PRIVATE_MAP_AUDIT_V1.ps1` as a single entrypoint for OWNER-local evidence, not an app installer. It accepts a **mandatory full commit SHA and exact historical snapshot ID**; it never chooses another archive by timestamp. A short, separately Git-blob-verified entrypoint must be delivered to the OWNER only after the CI-tested final commit and entrypoint blob are pinned.

The entrypoint uses pinned `raw.githubusercontent.com` content only to fetch these three **specific, separately Git-blob-verified executable scripts** into a new unique temporary folder: `VERIFY_V10_SNAPSHOT_RESTORE_REHEARSAL.ps1`, `VERIFY_V10_RESTORE_TARGET_MAP.ps1`, and `VERIFY_V10_ENCRYPTED_RESTORE_MAP.ps1`. A mismatched or oversized script aborts before execution, with no Git checkout/branch change. It deletes the temporary package at exit. Default `-Mode Inspect` performs read-only local snapshot verification and hashed source-target inventory. Optional `-Mode SaveAndVerify` additionally writes a Windows DPAPI **CurrentUser** encrypted map under `StateRoot/V10_private_restore_maps` and immediately invokes the independent same-user verifier; no plaintext target paths are printed or uploaded.

Desktop candidate roots are constrained to the current process's Windows known Desktop, its `USERPROFILE/Desktop`, `USERPROFILE/OneDrive/Desktop`, and Windows Public Desktop; they are deduplicated. The previous, OWNER-rejected separate-account setup is not searched or requested. Inaccessible roots are classified UNVERIFIED; the historical third Desktop remains unresolved and cannot be silently treated as empty.

All output is coarse stage/status/counts with `CUTOVER_ELIGIBLE=false` and `REAL_SUBMIT_ALLOWED=false`. Successful private-map preservation remains **PARTIAL_HOLD** for this historical snapshot. No process stop, CMD or shortcut replacement, live BRAIN/Excel/MS2 interaction, Git reset/branch update, automatic merge, restoration or actual trading is authorized. Windows synthetic tests use a CI-only fixture package path with exactly the same expected dependency blobs; the CI fixture mode is refused outside a Windows GitHub Actions job. They cover default no-write inspect, local DPAPI save/reverification, binary tamper rejection, missing snapshot, and no alteration of fake live entrypoints.

Important limitation: SHA-pinning a delivery script does not make it safe to execute an unreviewed unrelated script. The OWNER-facing paste must additionally verify the SHA-1 Git **blob** of the entrypoint before invoking it. Windows execution-policy bypass is limited to the child PowerShell invocation; never disable the system-wide policy. This is evidence-gathering only, **not** a substitute for a complete rollback plan or a release installer.

## P0-24 OWNER-authorized launch-route cutover (routing only, not app startup)

OWNER explicitly instructed us to perform the switch from the old `AI Cockpit START.lnk` -> DEBUG CMD -> Starter route to a pinned V10 entry. ChatGPT cannot directly change this PC without Windows computer-use access, and a Work handoff was declined. The route change is therefore a single OWNER-run, self-contained Windows PowerShell script, never represented as completed before OWNER's actual output proves it.

New `downloads/SWITCH_V10_OWNER_LAUNCH_ROUTE.ps1` exposes `-Mode Switch` and separately `-Mode Rollback`, and **never launches or kills any process**. It refuses if a V10 Controller state file exists, the V10 port set 28580–28584 is bound, or the process inventory identifies an already-running legacy/V10 Controller/observer. It never uses an old stop script as a generic process killer. Business Excel, MS2 and the pre-existing `C:\AI_Cockpit_Current\trade-cockpit` checkout remain untouched.

On Switch, the script stages a separate Git clone of the reviewed PR branch, verifies an exact full SHA, creates a separate local pinned branch, verifies BRAIN/STOP source markers, and generates separate **START/SAFE STOP CMD wrappers with an explicit exact SHA, branch, and repo root**. It backs up the existing English `AI Cockpit START.lnk`, writes temporary new shortcuts, then replaces exactly that startup link and adds `AI Cockpit V10 SAFE STOP.lnk`. The old route backup and an encrypted DPAPI CurrentUser receipt are retained under `StateRoot/V10_route_cutover_<random ID>`. Unknown extra Desktop roots are counted but never traversed to switch their shortcuts. The script cannot infer that there are no other stale links in an inaccessible Desktop.

Switch success must read `V10_ROUTE_SWITCH=PASS_NOT_STARTED` and `NO_APP_STARTED=true`: the only effect is that normal START points to pinned V10. **This is not successful V10 runtime acceptance.** Existing Desktop `AIコクピット_安全停止.cmd` and unrelated legacy desktop entries are not overwritten. The new dedicated stop shortcut is the only stop route associated with this staged installation, and it is still unverified against real in-session BRAIN/Excel. The separate DPAPI rollback action refuses if a running state/ports are detected and verifies hash equality of the old/current links before restoring. Its successful rollback result does not reverse any runtime MS2 Collector deployment or worker startup if those were independently performed after route switching. Do not run the new START merely because the link swap passes.

Windows synthetic CI uses a temporary local Git fixture plus fake disposable desktop shortcut and tests a pinned link swap, backup hash, new safe-stop shortcut, explicit rollback, bogus SHA refusal, and active-state refusal. It never starts real V10, Excel or MS2. The public GitHub CI result is necessary but is not proof of successful OWNER PC route replacement.

## P0-24B OWNER PC cutover blocked by persisted Controller state

OWNER's actual Windows attempt to run the SHA-pinned route switch printed `V10_ROUTE_BLOCK_STAGE=GUARDS`, `V10_ROUTE_BLOCK_REASON=ACTIVE_V10_STATE`, `V10_ROUTE_SWITCH=BLOCKED`, `SWITCH_EXIT=2`. This is fail-closed proof that the switch **did not occur**, but mere existence of `StateRoot/V10_CONTROLLER_STATE.json` does not prove any Controller, BRAIN, Excel or worker is still running. Do not delete this file, kill all Excel/python processes, or retry the old switch command.

The route switch now adds `-Mode InspectState` to classify the saved state using *strict* JSON parsing, required Controller/BRAIN/worker PID metadata, and OS-level process/PID inventory plus the original port and legacy script-identity checks. Without these checks it is still blocked. Missing or malformed JSON, incomplete tracked BRAIN identity, any retained PID currently occupied (including possible reuse by an unrelated process), listener on 28580-28584, or an unverified process command line remain fail-closed. `InspectState` is read-only. It outputs classification/status only, never paths, PID values or file contents.

An explicit opt-in `-ArchiveVerifiedStaleState` during `-Mode Switch` allows ONLY a fully verified dormant state file to be moved into the same newly created cutover evidence folder, SHA-256 checked, and recorded in the encrypted DPAPI CurrentUser rollback receipt. This occurs after staging the pinned release and backing up the old launcher, immediately before the route swap, with process/port checks repeated first. There is no blind deletion; if the route swap fails, the old state and shortcut are restored when possible. `-Mode Rollback` checks current link hashes and quiescence before restoring both the old launch link and the archived Controller state. Neither operation launches/stops processes or touches business Excel/MS2.

A successful route switch still means `PASS_NOT_STARTED`, not production V10 runtime acceptance. The previous OWNER checkout and already verified 11-file partial snapshot / encrypted location map remain untouched. The rejected alternative Windows account experiment remains excluded. Do not enable real order submission.

## P0-24C Real OWNER cutover blocked by incomplete Controller state

OWNER executed the 4ff959e8b56c7880053b805d457b58d60b050511 SHA-pinned Windows switch-preflight and obtained V10_ROUTE_BLOCK_STAGE=STATE_INSPECTION / V10_ROUTE_BLOCK_REASON=STATE_OWNERSHIP_INCOMPLETE / V10_ROUTE_SWITCH=BLOCKED / SWITCH_NOT_ATTEMPTED. This is a **correct fail-closed rejection**; no route switch or live V10 activation has been shown. It is not proof of a running BRAIN or Controller, and it is NOT permission to delete the state file or stop Excel/other Python processes.

`downloads/DIAGNOSE_V10_CONTROLLER_STATE_READONLY.ps1` was added as a separate, privacy-filtered preflight. It reads local V10_CONTROLLER_STATE.json without modification, checks required PIDs/session/started_at/repo/runtime field presence and validity, and checks whether recorded PIDs, V10 TCP listeners or recognizably named cockpit processes still exist. It reports ONLY the names of a fixed whitelist of missing/invalid state fields plus aggregate counts. It never prints PID values, account names, workbook names, machine paths, process command lines, state JSON or diagnostics exception content. No files/processes or Excel/MS2/worker state are changed. The output unconditionally contains CUTOVER_ELIGIBLE=false and REAL_SUBMIT_ALLOWED=false.

The current state must NOT be auto-migrated, reclassified as VERIFIED_DORMANT, deleted, force-stopped or archived on the basis of one missing field. An older schema may lack new BRAIN ownership metadata or a failed startup may have left repo_root/runtime_dir empty; neither is sufficient evidence of process absence. Only after OWNER-local read-only diagnosis is recorded may a minimal, independently tested compatibility gate be considered. The existing switch script remains strict, unchanged, and blocked for incomplete state. Old rejected separate-Windows-account use is not reinstated. A successful synthetic CI run does not constitute real-PC cutover.
