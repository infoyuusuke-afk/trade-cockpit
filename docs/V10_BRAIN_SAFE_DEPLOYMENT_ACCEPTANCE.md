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
