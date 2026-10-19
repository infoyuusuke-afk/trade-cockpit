# V10 Brain — private Windows acceptance verifier (research only)

PROJECT_ITEM_ID: P0-V10-BRAIN-RESEARCH-WINDOWS-ACCEPTANCE-20261020

## What is implemented
The independent opt-in verifier in scripts/v10_brain_research_windows_acceptance.py
performs two bounded read-only checks using an already-started, exact pinned
Windows V10 session. **It does not launch/stop the controller, start Excel,
schedule tasks, update the UI, or run trading code.** It does not read market
rows, account data or private ledger content for publication.

1. Invoke the existing, pinned, read-only
   downloads/AI_COCKPIT_V10_BRAIN_PREFLIGHT.ps1 in a new PowerShell process
   (no shell interpolation). It checks actual git HEAD/branch, controller
   ownership, health, local V10 runtime state, Brain process ownership,
   fresh observer output and immutable real_submit_allowed=false. Only a
   strictly whitelisted six-line stdout proof and a zero exit are accepted.
   A preflight failure is BLOCKED and no research data is read.
2. Read only the local V10_CONTROLLER_STATE.json in the selected state-root.
   Reject stale, changed, symlink/reparse/hardlink, oversized or malformed
   input. Match repo_root; extract runtime_dir and derive the exact
   ai_brain_observer_status_v1.json location. Verify that the
   Brain status engine_pid matches the Controller-recorded brain_observer_pid,
   then run PR #463's read-only sidecar against that status and PR #461's
   private context (validated by PR #462). After the sidecar, reread both
   the Brain status and Controller state and reject any detected switch or
   inconsistency. Accept only the restricted non-tradable research output.

No source material, file paths, strategy names, tickers, quote prices, PIDs
or account details appear in stdout. A failed check produces sanitized
BLOCKED/HOLD_RESEARCH and exit 2. A passing check produces
RESEARCH_OBSERVATION_ONLY and exit 0. This is only a point-in-time
research snapshot, **not proof of exchange timestamps, real fills, profit,
expectancy, authorization to trade or persistent liveness**.

## Windows usage after exact-head deployment review

V10 must already be running from the checked-out, independently accepted
commit. Use the actual local repo root, Controller state-root, and preselected
private Shadow directory; these paths remain private and are never copied to
GitHub. This command is not for execution during CI and must not be run on
the stopped V10 installation.

    python -B -m scripts.v10_brain_research_windows_acceptance --repo-root <absolute-v10-checkout> --state-root <absolute-controller-state-root> --research-private-dir <absolute-private-shadow-dir> --expected-sha <exact-40-character-HEAD> --expected-branch <exact-branch>

The existing source-pinned preflight must pass before any research read.
The prerequisite PR #461 one-shot producer is not started by the verifier.
A missing or stale context remains BLOCKED; the tool never repairs it,
resubmits an order or substitutes a cached success.

A passing snapshot is not a guarantee that a process remains alive
after the check. Because the Controller and Brain publish concurrently,
a legitimate update between the initial and final reads may also yield
BLOCKED. This is intentional fail-closed behavior, not a trade signal.

## Scope/acceptance

- Synthetic unit tests cover valid local read-only snapshot, no file changes,
  corrupted/stale input, forged status and PID, source-pin mismatch,
  source-authentication/real-order flag coercion, path injection, missing
  private data and subprocess isolation.
- Windows and Ubuntu CI runs exact PR HEAD. Windows also exercises the
  existing PowerShell preflight's own synthetic -SelfTest.
- The V10 31-file source-pin manifest and all pinned runtime files remain
  unchanged. No CSS/color/font/layout, Excel, Controller/Gateway, START/STOP,
  Watcher, Brain observer, task schedule, payment or real-order edits.
- This PR is stacked on Draft PR #463, then #462, #461 and their ancestors.
- OWNER Windows/MS2 real-machine acceptance: NOT_RUN. No private market
  observations have been inspected by this development process.
- Real order submission and every research promotion flag are always false.
- Verified realized P&L, fees, slippage, reproducible out-of-sample EV:
  UNKNOWN.

The work is not a replacement for a supervised read-only LIVE acceptance
after the parent Draft chain is approved and deployed safely. Do not present
a synthetic result as a verified real-market acceptance.
