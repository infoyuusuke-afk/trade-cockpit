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
