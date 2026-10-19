# V10 Brain opt-in research-only reader — independent Draft

PROJECT_ITEM_ID: P0-V10-BRAIN-RESEARCH-OPTIN-20261020

## Scope
This introduces an **optional** read-only private-research result field in the
existing independent scripts/ai_brain_observer.py. Its canonical Controller
startup does not pass the flag and therefore behaves identically to the former
observer. No running V10 deployment or Windows acceptance has occurred.

The opt-in CLI argument is --research-private-dir <absolute private directory>.
When selected, each Brain observation cycle reads only the exact
brain_research_context_v1.json produced by PR #461 in that selected directory,
through PR #462's strict consumer. No search, cache, regeneration, network,
timer, subprocess, private-data publication or order submission is added.

The optional field research_context in the **local Brain status file** is a
small allowlisted research state. It contains no tickers, prices, strategy
names, account IDs, paths, orders or virtual returns. It is independent from
the canonical OR15/VWAP observer fields and unrelated to the HTTP Gateway
contract. Malformed/unavailable input, a missing module, unexpected consumer
return shape, forbidden safety flag, stale file or exceptions become
BLOCKED/HOLD_RESEARCH, not a last-good signal. Every research output must
have literal real_submit_allowed=false, brain_trade_decision_eligible=false,
tested_expectancy_available=false, source_authenticated=false,
broker_fills_verified=false, costs_verified=false, promotion_eligible=false.

## Nondeployment, dependency, safety

- The controller and shortcut startup args are unchanged. Without the explicit
  flag there is no consumer import and no new research_context key.
- This does **not** schedule the PR #461 producer. A stale or missing producer
  output is intentionally BLOCKED, not silently refreshed.
- This is an input attachment for future research-only diagnostics, not
  autonomous strategy selection, a tradable market signal, statistically
  validated expectancy or order eligibility.
- No UI, CSS, layout, V10 Controller/Gateway/Watcher, Excel, source-pin
  manifest, service configuration, safe-stop, actual broker access, external
  network, recurring task or auto-merge is modified.
- Separate OWNER Windows/MS2 acceptance and exact-head CI evidence are
  necessary before any live opt-in use.

## Test approach

- Synthetic default launch retains the exact old status shape.
- A real file using PR #461's synthetic producer contract is consumed without
  rewriting source bytes or mtime.
- Missing, stale, corrupted context and a failing consumer block.
- Unexpected consumer output cannot leak private strings or promote a trade.
- CLI switch forwarding is verified. Windows+Ubuntu tests pin exact PR HEAD.

Current state: DRAFT, SYNTHETIC TESTING PENDING.
OWNER LIVE WINDOWS/MS2 ACCEPTANCE: NOT_RUN.
No trade, fill, expected return, revenue or 100億円 progress is claimed.
