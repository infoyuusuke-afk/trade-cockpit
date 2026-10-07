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
Cursor/Codex implement. Cloud/Work receive bounded execution tasks. Architecture/prioritization/acceptance remains centralized.

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
