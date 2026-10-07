# trade-cockpit: shared AI coordination

At the beginning of each Claude Code / Cursor / agent session in this repository, read these canonical files in this order:
1. docs/MASTER_PROJECT_STATE.md
2. docs/CURRENT_WBS.md
3. docs/DAILY_PROGRESS.md
4. docs/DECISIONS.md
5. STATUS.md
6. docs/AI_COCKPIT_MASTER_SPEC.md

## Mandatory priority rule
Every progress report starts with: 現実の紙幣 -> Project net P/L -> 100億円までの残額 -> 今日の実現利益/売上 -> 今日の実費 -> Owner労務コスト -> then technical progress / Acceptance / Blockers / Next actions.
Unknown money values must be marked 未集計 / 未確認. Never infer them.

## Single orchestration authority
Normal ChatGPT chat owns problem definition, prioritization, architecture, specification, Acceptance and integration.

Cursor / Claude Code / Work / Cloud are executors, not independent planners.
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

## Responsibilities
ChatGPT: architecture, prioritization, acceptance, integration.
Cursor / Claude Code: coding, tests, implementation from frozen spec.
Cloud / Work: bounded execution only; no independent architecture changes.
Owner: nearly zero-operation target.

A proposal or chat summary is not completed implementation. Verify source files, runtime state, timestamps, data, tests and acceptance evidence before PASS.

## Safety
real_submit_allowed=false unless explicitly approved. No global Excel kill. No global PowerShell kill. No MarketSpeed II force kill. PID-specific cleanup only after identity verification. Fail closed on stale/uncertain market data. Do not restore V8/V9 production runtime paths.

## Canonical sharing rule
Chats are not the project database. Durable state, decisions, blockers, acceptance results and economic facts must update the relevant canonical docs file. Do not create competing master files without explicit decision.

## Privacy
Never publish private MS2/Excel data, credentials, orders, personal holdings, or inaccessible local files to this public repo. Never turn model predictions into autonomous trade orders.
