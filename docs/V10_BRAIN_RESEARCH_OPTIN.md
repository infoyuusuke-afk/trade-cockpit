# V10 Brain research — independent opt-in read-only sidecar

PROJECT_ITEM_ID: P0-V10-BRAIN-RESEARCH-OPTIN-20261020

## Why the independent sidecar is required
The initial attempt to add an optional reader directly into scripts/ai_brain_observer.py
failed the V10 full-source-parity and candidate bundle tests. The 31-file V10
pinned source manifest and the baseline parity check intentionally prohibit
modifying this released core. The original script was restored **byte for
byte**, and the manifest was **not changed**.

The corrected implementation uses ONLY a new opt-in script,
scripts/v10_brain_research_optin.py. It reads the local published
ai_brain_observer_status_v1.json and the private context created by PR #461
through PR #462's validated reader. It emits only a sanitized, non-tradable
research decision to stdout and has no file-writing, network, broker, launch,
timer, polling, persistent-cache or process-control capability. This is a
research attachment, **not installed into, or automatically started with,
V10 Brain**. The canonical Controller and Brain observer remain unchanged.

## Manual opt-in (only after separate Windows acceptance)

From the exact reviewed checkout, using explicit owner-selected local paths:

    python -B -m scripts.v10_brain_research_optin --brain-status <absolute-runtime/ai_brain_observer_status_v1.json> --research-private-dir <absolute-private-shadow-dir>

The private Shadow directory must contain brain_research_context_v1.json.
The producer PR #461 remains independently opt-in; this sidecar never runs
it or refreshes missing/stale data.

## Fail-closed gates

- Absolute local filenames only; no UNC/device/symlinks/reparse/hardlinks,
  bounded (64 KiB) read, duplicate-key and nonfinite JSON rejection,
  before/after path-versus-descriptor identity checks.
- Handles the observed Windows NTFS st_ctime_ns discrepancy by comparing
  ctime only within identical stat APIs; continues checking file IDs,
  device, mtime, size, link count and same-API ctime change.
- Brain observer schema/role must match, state must be OBSERVATION_ONLY,
  exactly 100 observed rows, valid UTC-offset times, fresh publication,
  30-second Brain status and file freshness, no source authentication or
  promotion flags, no verified fills and no order permission.
- Private research consumer must independently validate its context,
  report RESEARCH_OBSERVATION_ONLY, and expose the exact safe/anonymous
  result schema with every execution/authentication/expectancy flag false.
- Any stale, malformed, missing, replaced or unsafe file, unexpected
  result, or error results in BLOCKED/HOLD_RESEARCH (CLI exit 2).
  Never reuse a prior success.
- Output only includes synthetic workflow state, reason, research decision,
  sample count, gates and permanently false safety flags. No market symbol,
  quote, strategy name, account, path or order details.

## Scope, validation and limits

- New code: scripts/v10_brain_research_optin.py
- Synthetic negative/positive tests: tests/test_v10_brain_research_optin.py
- Exact PR HEAD Ubuntu + Windows CI:
  .github/workflows/v10-brain-research-optin.yml
- Original pinned scripts/ai_brain_observer.py, Controller, Gateway, Watcher,
  START, STOP, the manifest, Excel, UI/CSS/colors/fonts/layout, live tasks,
  real-execution paths and credential configuration: **unchanged**.
- This reads unverified local publications, not proven exchange tick origin.
  Even a fully passing test does not prove live-market authenticity, strategy
  expectancy, costs, slippage, fills or economic return.
- This has no automatic research workflow or LIVE connection to the
  V10 controller. A separate reviewed integration and Windows/MS2 real
  acceptance would be required before that operational deployment.
- real_submit_allowed=false, brain_trade_decision_eligible=false,
  tested_expectancy_available=false, promotion_eligible=false at all times.

State: DRAFT / CI evidence required / OWNER Windows/MS2 Acceptance NOT_RUN.
Realized project P&L and progress to 100億円: UNKNOWN.
