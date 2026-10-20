# V10 Brain receiver for signed Agents SDK research

PROJECT_ITEM_ID: P0-AGENTS-SDK-V10-BRAIN-INTEGRATION-20261021
Stacked on Draft PR #481 (`draft/agent-sdk-coordination-pilot-20261020`).
Status: synthetic CI only. Not installed in the running V10. No order path.

## What it adds

PR #481 lets the Agents SDK sidecar write a signed research envelope
`agent_research_<run_id>.json` into an OWNER-selected private inbox. Nothing
on the Brain side received it. `scripts/v10_brain_agent_research_receiver.py`
is that receiving end:

| Step | Behaviour |
|---|---|
| Re-verify | HMAC, exact schema, safety flags, source binding, freshness (15 min), public HTTPS sources, release-time order, roles and NO_DATA rules, by the receiver process itself. The sidecar's own `*.ack.json` is never read or counted. |
| Store | Durable receipt in the private SQLite `brain_agent_research_receipts.sqlite` (BEGIN IMMEDIATE, synchronous=FULL, rollback journal). `real_submit_allowed` is constrained to 0 in the schema. |
| ACK | `agent_research_<run_id>.brain_ack.json`, `ack_kind=BRAIN_RECEIVER_ACK`, run_id, envelope SHA-256, received_at, receiver identity (component, receiver code SHA-256, process id), verification, state, reasons, roles, conflicts, `real_submit_allowed=false`. Signed, then read back independently. |
| Roles | Each role keeps exactly WATCH / NO_SIGNAL / NO_DATA. A failing envelope is BLOCKED as a whole. |
| Conflicts | Coordinator-reported conflicts and role status divergence are recorded, never resolved. |
| Duplicates | A run_id is received at most once (`DUPLICATE_REJECTED`). |
| Restart | Receipts and ACKs survive; an acknowledged envelope is not reprocessed; a modified ACK is reported. |
| Pending | `--status` lists inbox envelopes the receiver has not processed yet (Brain stopped). |

Research stays in the research lane: `data_lane=PUBLIC_RESEARCH_UNAUTHENTICATED_NOT_EXECUTION`,
`live_market_data=false`, `brain_trade_decision_eligible=false`. It is input
for Shadow and post-hoc review only.

## Unchanged

The 31 pinned V10 runtime files, the release manifest, Controller/START/STOP,
Collector, Gateway, Watcher, Brain observer, Shadow supervisor, Excel, UI,
colours, fonts, layout, scheduled tasks, Risk/Permission gates and Kill
Switch. No network, broker, subprocess, timer or paid API code.

## OWNER Windows check (only after OWNER approval of the exact SHA)

Uses saved public data and the offline runner: no OpenAI call, no cost.
`<PRIVATE>` is an OWNER-selected absolute folder outside the repository, for
example `D:\100億PROJECT\AGENT_RESEARCH_INBOX`. The key is a 64-hex secret
kept only on the PC (never in GitHub or chat).

```powershell
$env:AGENT_BRIDGE_HMAC_KEY = '<64 hex characters kept on this PC>'
cd <reviewed checkout of the approved SHA>
# 1) sidecar: offline coordination of the saved public file, then signed handoff
python -B scripts\agent_sdk_coordination_pilot.py --input examples\agent_sdk_public_synthetic_20261021.json --offline --handoff-dir <PRIVATE>
# 2) Brain receiver: receive once, then show receipts/pending
python -B -m scripts.v10_brain_agent_research_receiver --private-dir <PRIVATE> --once
python -B -m scripts.v10_brain_agent_research_receiver --private-dir <PRIVATE> --status
```

PASS on the PC means: `--once` shows `RECEIVED` for the run_id, the folder has
`agent_research_<run_id>.brain_ack.json` with `ack_kind=BRAIN_RECEIVER_ACK`,
and `--status` (run again after closing the window) lists the run_id under
`received_run_ids` with no `ack_mismatch_run_ids`. Run `--once` again: no new
result (already received). Exit code 2 / `BLOCKED` is a fail-closed result,
not a crash.

If the pilot CLI flags above differ in the reviewed SHA, follow
`docs/AGENT_SDK_COORDINATION_PILOT.md` for step 1; step 2 is unchanged.

## Limits

- HMAC proves possession of the local key, not official market truth. A
  privileged local process can forge files; this is not a sandbox.
- The receiver is a one-shot: it receives when run. It is not yet started by
  the V10 Controller; doing so is a separate, OWNER-approved change to pinned
  files.
- An envelope older than 15 minutes when the receiver runs is BLOCKED (stale),
  so the receiver must run soon after the sidecar.
- END_TO_END_VERIFIED requires the OWNER Windows run above; CI PASS is not it.

Actual revenue, realized P&L, costs, net profit and the remainder to 10 billion yen: UNKNOWN.
