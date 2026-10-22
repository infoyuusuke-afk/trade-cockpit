# 100億PROJECT — CURRENT WBS
Updated: 2026-10-18 JST
Source: COORD-V10-OWNER-FINAL-APPROVAL-20261018-V1, COORD-V10-ROADMAP-20261018-V1, COORD-V10-DATA-RIGHTS-ORDER-GATES-20261018-V1 (Issue #282)

> The 2026-10-08 WBS (P0-1 Brain continuous edge engine / P0-2 PF attribution / P0-3 NEXT-HOT / P0-4 V10 lifecycle) is superseded by the order below.
> Its specs (`docs/BRAIN_CONTINUOUS_EDGE_DISCOVERY_REALTIME_SIGNAL_SPEC_V1.md`, `docs/STRATEGY_PF_ATTRIBUTION_INVERSE_SHADOW_SPEC_V1.md`) remain only on the V10 branch line and are reconsidered in P1 or later.

All stages: `REAL_SUBMIT_ALLOWED=false`, `STOP_ALLOWED=false`, `CUTOVER_ELIGIBLE=false`. No auto-merge. No bulk merge of #418–#427.

| Stage | Work | Pass condition | Owner (primary) | Independent check | State (2026-10-18) |
|---|---|---|---|---|---|
| P0-1 | V10 localhost security fix | Reject Host/Origin spoofing, DNS rebinding, CSRF, non-allowlisted files, symlinks, misuse of `/control` `/speak` `/announce` | GPT development lead | Claude audit + GPT lead | Draft PR #441 (base #440, not main). Claude audit of old HEAD 1eb6dd5: CONDITIONAL PASS (3 findings). GPT fixed all 3 → new HEAD 44f417a, Windows/Ubuntu synthetic CI 9/9 PASS. Independent re-audit of 44f417a pending. Not verified on OWNER Windows |
| P0-2 | Unify V10 core on main | Correct start/stop, source pin, CI, independent acceptance | GPT development lead | GPT lead | Drafts #438 (STOP), #439 (source pin / guarded start), #440 (engine candidate), #441 (security) not integrated. #435 (P0-14) and #434 (legacy CI split) also Draft |
| P0-3 | Windows real-machine acceptance | Safe operation confirmed by an OWNER-approved procedure | GPT lead + OWNER | GPT lead | BLOCKED: P0-27 at ADMISSION. Issue #408 (P0-28) is a non-stopping diagnosis, waiting for instruction |
| P1-1 | Automated collection of licensed data | Source, retrieval time, usage rights and gaps verified | GPT development lead | GPT lead | Not started. Rights per source: DECISIONS.md D-019 |
| P1-2 | V10 screener + analyst AI integration | Supply/demand and PRE-NEXT predictions recorded reproducibly | GPT development lead / analyst GPTs | Specialist analysts | Not started. Display-only bridge first (ROADMAP G5) |
| P1-3 | Order draft → Shadow → phone approval (simulated) | One safe loop from OWNER approval to simulated execution | GPT development lead | GPT lead | Synthetic E2E Draft PR #442 (HEAD a221297, CI PASS). Paper-only simulated review: no authenticated phone, no actual Shadow fill, no real order |
| P2 | Limited real-order design and review | Independent acceptance + separate explicit OWNER approval | — | — | Not authorized |
| P3 | Full operation by track record | Risk, revenue and operating quality re-verified | — | — | Not authorized |

## Parallel / maintenance
- Canonical ledger unification: Draft PR #443 prepared, pending merge (Claude is the sole editor; GPT lead reviews the exact HEAD; OWNER approves the merge).
- Document sync after each formal Issue #282 decision: D-022.
- Legacy V8/V9 test isolation: Draft PR #434. Merge awaits GPT lead approval.
- Revenue lane: must not be starved. Record actual cash only, never projected value.

## 2026-10-22 additions (Issue #282 comment 6335516423, PENDING_DOC_SYNC)
- Post-close audit repairs, D-035 scope, on the PR #488 line from 08c1479. The Claude on the OWNER PC drafts. Claude audits independently. Switching the live machine needs OWNER approval.
  - Gateway cache
  - browser speech removal
  - 期待値 / 順位スコア labels
  - after-15:30 downtime exclusion
  - S1-S3 Excel order
- Design only: per-symbol LIVE status (D-040); stale and empty tab cleanup table (D-042).
- Paid GPT ledger hardening before any new paid run (D-041). Owner: GPT lead; independent acceptance required.
- Supply/SQ checklist C01-C10 (D-043): design recorded; API wiring by the PC Claude after separate authorization.
- Market regime research subsystem (D-044), P1. Phase 0 read-only log inventory (PC Claude), then offline classifier/backtest, then independent review (cloud Claude). R2 and its 60-min hold unchanged.
- Deferred, medium:
  - slippage in EV
  - Excel-busy Shadow pauses
  - afternoon cycle time
  - tick-rounded stop/target
  - Brain vs Shadow time basis
  - JPX data age

## Owner operation target
Nearly 0. Repeated manual PowerShell/debug loops are a system failure, not normal operation.
