# 100億PROJECT — DECISIONS
Updated: 2026-10-18 JST

> D-001〜D-016 were recorded on 2026-10-08 on the V10 branch line and are carried to `main` unchanged, except D-002, D-005 and D-016 are annotated below (the original text is kept).
> D-017 onward summarize later formal decisions; the full text is the Issue #282 record named in each entry.

## D-001 Money before technology
Every progress report starts with real cash and P/L. Technical completion never counts as revenue.

## D-002 GitHub is canonical shared state
Cross-agent state belongs in MASTER_PROJECT_STATE.md / CURRENT_WBS.md / DAILY_PROGRESS.md / DECISIONS.md. Chats are not the canonical project database.
2026-10-18 annotation: PR #443 brings these files to `main` (previously they existed only on unmerged V10 branches). Issue #282 `[100B_COORD_V1]` records hold the detailed history.
Precedence: the `main` files are the last ACCEPTED snapshot. A later traceable formal decision on Issue #282 takes precedence but is `PENDING_DOC_SYNC` until it is checked into `main`, and it never removes an OWNER approval condition it states. See D-022.

## D-003 V10 only in production
Do not restore V8/V9 active runtime paths. Git history is sufficient for old-code recovery/audit.

## D-004 Owner nearly zero-operation
Owner should not become the default debugger. Repeated manual PowerShell, screenshots and process cleanup are a system failure condition.

## D-005 Bounded executors
Cursor/Codex implement only after the normal-chat orchestrator fixes objective, specification and Acceptance.
Cloud/Work execute only bounded tasks that genuinely require local/browser/GUI/file capability.
Executors must not independently redesign architecture, reprioritize the project, or redefine success.
2026-10-18 annotation: role assignment updated by D-020 (GPT development lead is primary implementer; Claude is independent audit / limited assigned support; Cursor not assumed).

## D-006 Lifecycle acceptance
No PASS from START alone. Required lifecycle: START -> RUNNING -> STOP -> CLEAN -> RESTART.

## D-007 Real order lock
real_submit_allowed=false remains mandatory until separately approved by explicit acceptance.

## D-008 Fail closed
If price source, workbook identity, freshness, process identity or data conflict is uncertain, block trading output.

## D-009 Logs over dead files
Retain durable logs/evidence; remove obsolete active backup copies. Git history is the recovery path for superseded source.

## D-010 NEXT/HOT target behavior
EVENT 5 must evolve to: market-wide discovery -> candidate promotion -> live enrichment -> ranked display -> replay/Shadow evaluation.

## D-011 No local optimization trap
At each prioritization point evaluate actual cash impact, blocker severity, Owner labor, time-to-completion, opportunity cost, and parallelizable revenue work. Do not let one technical defect consume all project capacity indefinitely.

## D-012 Normal-chat-first orchestration
The normal ChatGPT chat is the single orchestration layer.
Before any handoff, it must define:
- why the task matters to money / P0,
- confirmed facts and unknowns,
- exact inputs,
- exact outputs,
- calculation/decision rules,
- safety constraints,
- Acceptance / DoD,
- next-action owner.

Do not hand off analysis, reporting, comparison or specification work merely for convenience.
First exhaust repository/shared logs/connected evidence available to normal chat.

## D-013 Executor output is evidence, not authority
Work/Cloud/Cursor results are not automatically accepted project truth.
They return bounded execution evidence.
Normal chat verifies that evidence against the frozen specification and Acceptance before updating canonical state.

## D-014 No cascading handoffs
One executor must not delegate to another executor or create a parallel architecture branch unless the canonical spec explicitly authorizes it.
If execution reveals a missing requirement, stop at the boundary and return the gap to normal chat for specification update.

## D-015 Prevent specification drift
Do not create a new format, new KPI, new architecture, new role split or new definition of done during execution.
If a change is justified, record it first as a decision in DECISIONS.md, then update the relevant spec, then implement.


## D-016 Brain is the continuous edge-discovery and realtime-selection authority
The Brain is not a fixed 8-Supervisor committee and not a health dashboard.
Its canonical role is to continuously discover permitted trading methods, normalize and validate them, learn context-specific expected value, select the best current strategy/symbol during market hours, and publish LONG / SHORT / NO-TRADE advisory signals with complete evidence.
The number of strategies and strategy modules is dynamic and evidence-driven.
Existing strategy Supervisors are internal specialist modules, not a fixed target roster.
Shadow measures Brain decisions and feeds performance back; it does not replace Brain decision ownership.
`real_submit_allowed=false` remains mandatory.
2026-10-18 annotation: D-016 is the target architecture, not the implemented state. The actual V10 BRAIN observer is not yet the continuous live strategy-selection authority.


## D-017 One AI per PR / file set
Only one AI edits a given PR or file set at a time. Changing the owner requires the GPT lead to name the handover point.
Source: Issue #282 COORD-V10-OWNER-FINAL-APPROVAL-20261018-V1 §6; OWNER instruction 2026-10-17 after a concurrent-edit collision on PR #434.

## D-018 V10 release roadmap
Order: G0 inventory/freeze → G1 independent security/source review → G2 UI evidence truth (28584 is a Gateway, not the BRAIN worker; BRAIN LIVE must not derive from shadow/fail_closed alone; stale data never shown as fresh) → G3 read-only OWNER preflight (separate approval) → G4 data provenance → G5 analyst bridge phase A (display only, no Brain input) → G6 phase B Brain advisory (separate approval, never broker submit).
Do not bulk-merge the older #435–#437 history.
Source: Issue #282 COORD-V10-ROADMAP-20261018-V1.

## D-019 Data rights for machine processing
- MS2 RSS (permitted usage) is the primary machine-processed trading data source.
- Official data (JPX, TDnet, EDINET) only source-by-source after machine access, AI analysis, storage and redistribution rights are reviewed. Publicly readable ≠ reusable. TDnet API fees need OWNER approval. EDINET API requires registration and attribution.
- TradingView charts, alerts, webhooks, CSV and MCP data are human-display-only. They are not input to strategy, signals, order drafts or verification without rightsholder permission.
- 会社四季報オンライン: VIEW_ONLY / AI_IMPORT_BLOCKED until its paid-membership terms and written authorization are verified. Manual transcription does not override the license. Issue #293's manual-import idea is not permission.
- US regime monitoring uses temporary alternative A: MS2 domestic overnight futures/FX as imperfect proxies. Option B (a licensed API) needs value proof, legal clearance and OWNER payment approval.
- No paid source before measured ROI and OWNER authorization.
Source: Issue #282 COORD-V10-DATA-RIGHTS-ORDER-GATES-20261018-V1.

## D-020 AI-max automation with OWNER final approval
V10 target: AI automates data → analysis → candidates → risk → order drafts → safety checks → Shadow → evaluation/reports. The OWNER only approves or rejects on a phone, and handles exceptions.
- AI working automatically is separated from AI placing real orders.
- Approval binds symbol, side, quantity, price, order type, stop condition, risk amount and the proposal hash. Any later change invalidates it.
- Approval requires an authenticated device and a verified session. The `decided_by="OWNER"` string alone is insufficient.
- Display time and order-permission time are separate. The existing 15-second ticket freshness is not relaxed. Price and risk are re-evaluated at approval.
- Emergency stop first revokes new-order permission. Process stop, order cancellation and position handling have separate safety conditions.
- REAL_SUBMIT_ALLOWED stays false through data, analysis, order drafts, Shadow and simulated phone approval. Future unlocking is never a global flip to `true`. It is a separately designed, scoped permission requiring a formal diff spec, independent acceptance and OWNER approval.
- Roles: GPT development lead is the primary implementer. GPT lead freezes specs and promotes stages. Claude provides independent audit and limited assigned support. Cursor is not assumed.
Source: Issue #282 COORD-V10-OWNER-FINAL-APPROVAL-20261018-V1.

## D-021 V10 localhost security is release-blocking
Before expanding sensitive local data or adding any execution path:
- remove broad cross-origin access to the local Gateway, Collector, Watcher and Voice
- enforce allowlisted Host/Origin, loopback-only and read-only routes, and a strict static-path allowlist
- add negative adversarial tests (DNS rebinding, CSRF, symlink)
Browser-reachable control functions must not be grown into the order-approval function.
Source: Issue #282 COORD-V10-DATA-RIGHTS-ORDER-GATES-20261018-V1 §4 and COORD-V10-OWNER-FINAL-APPROVAL-20261018-V1 §2.

## D-022 Precedence of Issue #282 decisions and document sync
- The `main` canonical documents are the last ACCEPTED snapshot.
- A later formal decision on Issue #282 takes precedence only if it is traceable (it has a record_id and is recorded as an OWNER instruction or a GPT lead formal decision). Until it is checked into `main`, its state is `PENDING_DOC_SYNC`.
- Precedence never removes an OWNER approval condition stated in that decision. A role label alone does not substitute for OWNER approval.
- Not every Issue #282 comment is a formal decision. A new PR is not the `main` state until it is merged.
- Sync procedure: after a formal decision, the GPT lead names one document owner (one AI). That owner updates DECISIONS.md, CURRENT_WBS.md and DAILY_PROGRESS.md in one Draft PR. The GPT lead reviews the exact HEAD, and the OWNER approves the merge. No auto-merge.
- Editing these documents does not by itself start work by any other AI.
Source: PR #443 review P443-GPT-INDEPENDENT-REVIEW-20261018-V1 (GPT lead, 2026-10-18), items 3 and 6.

## D-023 V10 runs with no other Excel in use
- While AI Cockpit V10 is running, the OWNER does not use any other Excel file in the same Windows session. V10's Excel is the only Excel.
- Controller startup: if another Excel process exists in the session, refuse to start and show "Close other Excel files, then start again." Never close, kill, save or click that Excel.
- Safe Stop: if another Excel exists, refuse to stop anything and show the same reason. This refusal is the intended behavior, not a defect.
- This supersedes the earlier V10 design assumption "foreign Excel may stay open" (Controller code from 2026-10-07, carried into PR #444).
Source: OWNER instruction (given earlier in chat, restated 2026-10-18 16:26Z in the Claude audit thread); PR #445 independent audit P1 (Claude, 2026-10-18).

## D-024 OWNER instructions must be recorded before implementation
- An OWNER instruction that changes an operating assumption, a safety rule or acceptance is not in force for the AIs until it is recorded here as a D-number with its source. A chat-only instruction is not seen by the next AI session.
- When an AI receives such an instruction in chat, it records it in a docs-only Draft PR (D-022 procedure) or asks the GPT lead to do so, before building on it.
- Before implementing or auditing, check the design assumption against DECISIONS.md. If code contradicts a recorded decision, report the contradiction instead of silently following the code.
Source: OWNER instruction 2026-10-18 16:32Z ("食い違いが起きないよう修正しなさい") after D-023 was found missing from all canonical records.
