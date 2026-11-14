# trade-cockpit: shared AI coordination

At the beginning of each Claude Code / Cursor / agent session in this repository, fetch the current `main` where safe and do not overwrite uncommitted work. Then read these canonical files in this order:
1. docs/MASTER_PROJECT_STATE.md
2. docs/CURRENT_WBS.md
3. docs/DAILY_PROGRESS.md
4. docs/DECISIONS.md
5. STATUS.md (short entry point; history in docs/history/STATUS_ARCHIVE_UNTIL_2026-09-24.md)
6. docs/AI_COCKPIT_MASTER_SPEC.md
7. The latest `[100B_COORD_V1]` records in Issue #282.

The files above are the last ACCEPTED snapshot. A later traceable formal decision in Issue #282 takes precedence but stays `PENDING_DOC_SYNC` until it is checked into `main`. Precedence never removes an OWNER approval condition, and a role label alone does not replace OWNER approval. Not every comment is a formal decision, and an unmerged PR is not the `main` state. See docs/DECISIONS.md D-022 for the sync owner and reviews. OWNER instructions that change an operating assumption take effect for AIs only once recorded as a D-number (D-024). Check code assumptions against DECISIONS.md before implementing or auditing; for example, V10 runs with no other Excel in use (D-023).
Editing these documents does not by itself start work by any other AI.

## Mandatory priority rule
Every progress report starts with: 現実の紙幣 -> Project net P/L -> 100億円までの残額 -> 今日の実現利益/売上 -> 今日の実費 -> Owner労務コスト -> then technical progress / Acceptance / Blockers / Next actions.
Unknown money values must be marked 未集計 / 未確認. Never infer them.

## Single orchestration authority
Normal ChatGPT chat (GPT lead) owns problem definition, prioritization, architecture, specification, Acceptance and integration.

GPT development lead is the primary implementer (D-020).
Claude / Claude Code provides independent audit and limited support on stages the GPT lead assigns.
Cursor is not assumed. Work / Cloud is for bounded execution only.
Executors do not independently plan.
Do not reinterpret vague requests into a new architecture.
Do not change priorities, KPIs, Definition of Done or system roles during execution.

A task is executable only when the handoff packet states:
- objective / economic reason,
- confirmed facts and unknowns,
- exact inputs,
- exact outputs,
- implementation or calculation rule,
- safety constraints,
- Acceptance / DoD.

If any of these are materially missing, return the gap rather than inventing it.

## Handoff discipline
Normal chat should not hand off analysis/reporting/calculation/specification merely because another executor exists.
Use Work/Cloud only for bounded operations that truly require local PC, GUI, browser or file access.
Use Cursor/Claude Code only after the implementation specification is frozen.

Executor output is evidence only. It is not accepted project truth until normal chat verifies it against Acceptance and updates canonical state.

No cascading handoffs between executors unless explicitly authorized in the canonical spec.
Only one AI edits a given PR or file set at a time (D-017).

## Responsibilities
ChatGPT lead: architecture, prioritization, acceptance, integration.
GPT development lead: primary implementation.
Claude Code: independent audit; coding and tests from a frozen spec when assigned.
Cloud / Work: bounded execution only; no independent architecture changes.
Owner: nearly zero-operation target; final approval and unavoidable local confirmation only.

A proposal or chat summary is not completed implementation. Verify source files, runtime state, timestamps, data, tests and acceptance evidence before PASS.

## Safety
real_submit_allowed=false unless explicitly approved. No global Excel kill. No global PowerShell kill. No MarketSpeed II force kill. PID-specific cleanup only after identity verification. Fail closed on stale/uncertain market data. Do not restore V8/V9 production runtime paths.

## Canonical sharing rule
Chats are not the project database. Durable state, decisions, blockers, acceptance results and economic facts must update the relevant canonical docs file. Do not create competing master files without explicit decision.

Shared-sheet bridge: if an actionable docs/AI_SHARED_SHEET.md row is relevant, record its ID and status in docs/CLAUDE_BRIDGE_RESPONSES.md, referring to the source row. Status values: accepted, declined with reason, needs evidence, implemented with commit/test reference. Do not delete existing rows or silently close another agent's work.
The opt-in scheduled review setup is documented in docs/CLAUDE_ROUTINE_BRIDGE.md. This file alone does not activate it.

## Privacy
Never publish private MS2/Excel data, credentials, orders, personal holdings, or inaccessible local files to this public repo. Never turn model predictions into autonomous trade orders.
