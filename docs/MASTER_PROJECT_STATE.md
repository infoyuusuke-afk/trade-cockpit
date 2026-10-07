# 100億PROJECT — MASTER PROJECT STATE
Updated: 2026-10-08 JST
Status: ACTIVE
Authority: Canonical cross-agent project state

## MASTER MISSION
100億円を稼ぐシステムをAIと作る。
手段は固定しない。期待値・収益化速度・再現性・Owner労務削減を継続評価する。

## 0. 現実の紙幣 — 最上位KPI
このセクションを技術進捗より必ず先に読む。

- Project revenue actually received: **0円 confirmed**
- Project realized trading profit: **0円 confirmed in current project accounting**
- Project operating cost: **未集計**
- Owner labor cost: **未集計**
- Project net P/L: **未確定。少なくとも黒字化未達**
- Owner-reported historical trading loss before/alongside project: **3,500万円超**
- 100億円 target remaining: **100億円 + 未集計のProject赤字**
- Rule: 技術完成度を現実の利益として計上しない。紙幣・実現損益だけを収益KPIとする。

## 1. Current P0
1. AI Cockpit V10 lifecycle stabilization and verification
2. NEXT/HOT real-time market-wide detection lane
3. Trading data quality / fail-closed / Shadow track record
4. Revenue-producing lanes must not be starved by endless local debugging

## 2. Confirmed V10 state
- V10 START acceptance: PASS
- V10 STOP acceptance: PASS
- Local runtime folder cleanup: PASS
- Re-start core processes observed live after STOP
- Full lifecycle final confirmation remains dependent on post-restart Brain full-state verification
- real_submit_allowed=false
- V8/V9 production runtime paths are not to be restored

## 3. Known current gap
EVENT 5 / HOT銘柄 is **not yet a true market-wide real-time lane**.
Current UI uses `speculative_theme_watch` static/current scan data and does not yet complete:
market-wide scan -> HOT promotion -> MS2 RSS live promotion -> real-time tracking -> EVENT 5.

## 4. Architecture ownership
- ChatGPT normal chat: single orchestration authority for problem definition, priorities, architecture, specification, acceptance, and integration.
- Cursor/Codex: implementation only after specification and Acceptance are fixed.
- Cloud/Work: bounded execution only when local/browser/GUI/file access is truly required; no architecture, no reinterpretation, no priority changes.
- Owner: should be nearly zero-operation; only unavoidable local confirmation / approval.

## 4.1 Mandatory handoff gate
**Do not hand work to Work/Cloud/Cursor merely because they are available.**
The normal-chat orchestrator must first complete, in writing:
1. objective and economic reason,
2. exact current facts / unknowns,
3. input data source,
4. required output,
5. algorithm / decision rule when applicable,
6. safety constraints,
7. Acceptance / Definition of Done,
8. owner of the next action.

Handoff is allowed only if the remaining task requires capability that normal chat cannot execute directly, such as local-PC/GUI/browser/file operations or bounded implementation.

The executor must receive a frozen task packet and must not redesign it.
Executor output is evidence/results only; it does not become architecture or project truth until normal-chat Acceptance checks it and updates canonical state.

For analysis/reporting/calculation requests, first use available shared logs, repository data, connected sources, and existing evidence. Do not escalate to Work by default.

## 5. Canonical runtime
Repository: `infoyuusuke-afk/trade-cockpit`
Branch: `cursor/p0-stale-price-failclosed-d483`

Core V10 runtime:
- downloads/RUN_AI_COCKPIT_V10.ps1
- downloads/AI_COCKPIT_CONTROLLER_V10.ps1
- downloads/STOP_AI_COCKPIT_V10.ps1
- downloads/AI_COCKPIT_GATEWAY_V10.ps1
- downloads/AI_COCKPIT_VOICE_BRIDGE_V10.ps1
- downloads/EXCEL_IDENTITY_PROBE_V10.ps1
- downloads/START_AI_COCKPIT_V10.cmd
- downloads/STOP_AI_COCKPIT_V10.cmd
- index.html
- active Watcher / Collector / Heartbeat / Shadow components

## 6. Safety rules
- real_submit_allowed=false
- no global Excel kill
- no global PowerShell kill
- no MarketSpeed II force kill
- exact PID identity before force cleanup
- no startup git mutation
- fail closed on uncertain data identity or stale market data

## 7. Mandatory reporting order
Every project progress report must begin with:
1. 現実の紙幣
2. Project net P/L
3. 100億円までの残額
4. 今日の実現利益 / 売上
5. 今日の実費
6. Owner労務コスト
7. Only then technical progress / Acceptance / Blockers / Next actions

Unknown values must be marked 未集計/未確認. Never invent them.

## 8. Canonical supporting documents
- docs/CURRENT_WBS.md
- docs/DAILY_PROGRESS.md
- docs/DECISIONS.md
- docs/AI_COCKPIT_V10_INCIDENT_AND_FIX_LOG.md
- docs/AI_COCKPIT_V10_CLEANUP_LOG.md
- docs/AI_COCKPIT_V10_LOG_POLICY.md


## 3.1 Canonical Brain definition
Brain is the 365-day continuous edge-discovery and realtime strategy-selection authority.
It continuously discovers permitted strategy ideas, validates them with point-in-time-safe evidence, maintains context-specific Champion/Challenger rankings, and during the TSE session publishes the best eligible symbol + LONG / SHORT / NO-TRADE advisory signal.
The strategy roster is dynamic; the existing 8 strategy Supervisors are not a permanent target count.
Shadow is the attributed measurement/feedback layer for Brain decisions.
Canonical detailed spec: `docs/BRAIN_CONTINUOUS_EDGE_DISCOVERY_REALTIME_SIGNAL_SPEC_V1.md`.
