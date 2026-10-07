# 100億PROJECT — DECISIONS
Updated: 2026-10-08 JST

## D-001 Money before technology
Every progress report starts with real cash and P/L. Technical completion never counts as revenue.

## D-002 GitHub is canonical shared state
Cross-agent state belongs in MASTER_PROJECT_STATE.md / CURRENT_WBS.md / DAILY_PROGRESS.md / DECISIONS.md. Chats are not the canonical project database.

## D-003 V10 only in production
Do not restore V8/V9 active runtime paths. Git history is sufficient for old-code recovery/audit.

## D-004 Owner nearly zero-operation
Owner should not become the default debugger. Repeated manual PowerShell, screenshots and process cleanup are a system failure condition.

## D-005 Bounded executors
Cursor/Codex implement only after the normal-chat orchestrator fixes objective, specification and Acceptance.
Cloud/Work execute only bounded tasks that genuinely require local/browser/GUI/file capability.
Executors must not independently redesign architecture, reprioritize the project, or redefine success.

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
