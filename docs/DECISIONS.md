# 100億PROJECT — DECISIONS
Updated: 2026-10-22 JST

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

## D-025 One-time OWNER exception: trial of unaccepted PR #446 (2026-10-19)
- On 2026-10-19 the OWNER approved, in chat, one trial of the unaccepted PR #446 commit ab350d28e2d116d468d4e6bcd9bacd6f5538b6c2 on the OWNER PC, with real_submit_allowed=false. Startup failed closed (an untracked required helper was missing); the day ran on the existing V10.
- This was one exception. It is not an independent acceptance, a standing waiver, a cutover or a merge approval.
- Any later trial first re-verifies the source pin, the tracked bundle, STOP and rollback, the exact HEAD and the permission boundary, and needs the OWNER's explicit approval again.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: Issue #282 DEV-D025-D026-V10-MARKET-OPERABILITY-20261019 (GPT lead, recording the OWNER report).

## D-026 V10 market operability: staged plan C
- Plan A first: observe every symbol with its own freshness; derive metrics and candidates only from verified, time-consistent inputs. An unknown or stale candidate, and any aggregate without verified input lineage, stays BLOCKED.
- Plan B (replacing watchlist symbols) waits for multi-day evidence and OWNER approval. No automatic removal of symbols.
- 99/100 is never treated as complete. Keep the original expected universe, missing-data and coverage counts, provenance and available_at.
- The existing whole-board fail-closed rule stays until a partitioned computation is proven by negative tests. Shadow and paper only; real_submit_allowed=false; no wider trading permission.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: Issue #282 DEV-D025-D026-V10-MARKET-OPERABILITY-20261019 (GPT lead formal decision).

## D-027 V10 watchlist: delisted code replaced by its successor listing (2026-10-19)
- Change: `QPS研究所（5595）` / `5595.T` → `QPSホールディングス（464A）` / `464A.T` in `ms2_live/watchlist_100.json`, same slot and order, other attributes unchanged.
- Reason: the company moved to a holding-company structure. The old code was delisted on 2025-11-27 and the successor was listed on 2025-12-01 (1:1). MarketSpeed II RSS returns empty cells for the old code, so the V10 board was always 99/100.
- OWNER approval: 2026-10-19 07:01Z (decision card, "置き換える"). On 2026-10-19 07:14Z the OWNER also approved the narrow CI source-pin exception for this one file.
- This is a code change for the same listed business, not a Plan B universe removal or substitution. D-026 still governs any other watchlist replacement.
- Implementation: Draft PR #451 (stacked on #446).
  - HEAD e208c6eb2f7209f4e4870a2b18c265ad698c3f61
  - Watchlist blob `ecff9eed20478bfe2b74b68dbbcf1cbc811fba38`, equal to its pin in `downloads/V10_RELEASE_BUNDLE_MANIFEST.json`
  - The CI exception is limited to this file: manifest pin equals HEAD blob, 100 entries, original order, exactly this one change, unique tickers. It is enforced by `scripts/ci_v10_watchlist_replacement.py`, with negative tests in `tests/test_v10_watchlist_replacement.py`.
  - Synthetic CI 9/9 SUCCESS at e208c6eb.
  - Duplicate PR #452 closed unmerged.
- Not done: Windows real-machine acceptance (NOT_RUN), the OWNER workbook switch, cutover, merge.
- The workbook rows (the 100-symbol RSS sheet and any other sheet holding the old code) switch together with the runtime that uses this list. Switching only one side fails closed with ROW_SHEET_CODE_MISMATCH. Shadow and paper only; real_submit_allowed=false.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: OWNER chat and decision card on 2026-10-19 in the Claude project thread (D-024), plus GPT lead instruction P0-V10-WATCHLIST-464A-SOURCE-PIN-20261019.

## D-028 V10 runs from the fixed line only; trial of #446 approved (2026-10-19)
- OWNER instruction, 2026-10-19 08:10Z: "修正版で起動して、おかしなところがあればなおす、古いのはもう起動させない".
- The previous installed V10 (pre-#446) is retired. AIs must not start it, and must not propose it as an option. Its folder stays only as a rollback copy and evidence.
- The OWNER approves a trial of the #446 line (HEAD 65d6015b0c6bbd8e53f926baac0fbb8527798c0e at approval time) on the OWNER PC from a separate folder, with real_submit_allowed=false, Shadow and paper only. Defects found in the trial are fixed on the owning PR with negative tests and CI, then re-tried.
- This is not an independent acceptance, a merge approval or a cutover. D-025 stays a separate one-time record. D-023 (no other Excel) and D-027 (the workbook switches together with the watchlist) still apply. The watchlist and workbook stay on the old code until a runtime HEAD that carries #451 is approved.
- Open point for the GPT lead: if the fixed line cannot start on a trading day, V10 does not run that day. The old line is not a fallback.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: OWNER chat 2026-10-19 08:10Z in the Claude project thread (D-024).

## D-029 Specialist AIs report to Issue #282 on their scheduled runs; the coordinator ACKs (2026-10-19)
- Evidence, 2026-10-19, one-shot interactive tests approved by the OWNER on decision cards:
  - Revenue Hunter, PRE-NEXT and the supply/SQ analyst each wrote one exact public-safe comment to Issue #282 with their own GitHub connector (6264610794, 6264616075, 6264617113). No safety block reproduced.
  - The coordinator posted one ACK per report (6264654527, 6264655210, 6264655879).
  - Each specialist re-read its own ACK and quoted its message_id and comment URL.
  - This is a full round trip, interactive only.
- OWNER decision, 2026-10-19 10:05Z ("伝える"): the earlier WRITE_UNAVAILABLE status is lifted for these three roles. Each scheduled run must:
  - read #282 first
  - post at most one public-safe REPORT, and only on MATERIAL_CHANGE
  - cite the last ACK it read in `in_reply_to`
  - on any denial, stop without retry, edit or channel switch
- The coordinator ACKs each unanswered REPORT once per run.
- Schedules, enablement and notification settings are unchanged. The rule is given as a one-time chat message in each task.
- Still open:
  - END_TO_END_VERIFIED needs one scheduled-run round trip without OWNER relay.
  - Role identity stays UNVERIFIED, because all roles post under one GitHub account.
  - real_submit_allowed=false.
- Amendment, 2026-10-19 10:19Z (OWNER decision card "このまま使う"): after the chat rule, Revenue Hunter itself updated the prompt of its existing hourly task to read #282 first, post at most one REPORT on MATERIAL_CHANGE and re-read it. Its schedule (hourly, condition_watch), ON state, notifications OFF and real_submit_allowed=false are unchanged. This departs from the standing rule that hourly task prompts are not changed, and the OWNER approved keeping it. PRE-NEXT made the same kind of update to its hourly task prompt at about 10:20Z. Its hourly run at :44:09 JST, ON state and notifications OFF are unchanged. The OWNER was informed in the thread and may revert it. The supply/SQ analyst acknowledged the rule in chat and did not report a prompt change. The coordinator likewise added "read #282 first, ACK each unanswered specialist REPORT once, re-read" to its existing hourly task (schedule, ON, notifications OFF unchanged), reported to the OWNER at about 10:21Z.
- Result, 2026-10-19 (OWNER screenshots): scheduled-run writes are BLOCKED. Revenue Hunter (up to 21:00 JST, twice) and PRE-NEXT (22:50 JST, one REPORT attempt PRENEXT-RUN-2026101922-01) got "This tool call was blocked by OpenAI's safety checks. Please double check what you are sending." Both stopped without retry, rewording or a channel switch. Scheduled-run reads of #282 and of the coordinator ACK work. Supply/SQ is not observed. END_TO_END_VERIFIED: none. Recorded on #282 (6269074696). The OWNER chose to keep the hourly prompts unchanged until the GPT lead decides another upward route.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: OWNER decision cards 2026-10-19 09:59Z and 10:05Z in the Claude project thread (D-024); P0-AI-COORDINATION-DELIVERY-RECOVERY.

## D-030 Claude builds a parallel "Claude Brain" as TradingView Pine Script strategies (2026-10-19)
- OWNER instruction, 2026-10-19 15:20Z: "GTPブレインと並行してクロードブレインを育成しろ、こちらはトレーディングヴューのパインスクリプトとしてバックテスト検証をする、PFがよければザラバ中におれが試す".
- Claude writes trading-signal strategies in Pine Script. The OWNER runs them in TradingView's Strategy Tester and sends back the numbers (symbol, timeframe, period, PF, trade count, win rate, max drawdown).
- If the PF is good, the OWNER may try the signal by hand during the trading session. That is the OWNER's own manual trading. No AI sends orders. real_submit_allowed=false is unchanged.
- This track is separate from V10 and the GPT Brain. It changes no V10 code, task, schedule or Excel. TradingView data is not fed into V10 or BRAIN automatically (TradingView terms; only the OWNER's reported numbers are used).
- Claude's proposed pass bar, not a decision: PF >= 1.3 with at least 100 trades, PF > 1.0 in both halves of the period, and a similar result on 2-3 symbols. Parameter changes are counted to limit overfitting.
- Working files: the Claude on the OWNER PC owns the strategy (Desktop folder "Claudeブレイン", CB1 v1 and later). The cloud Claude audits. Not in this public repo.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: OWNER chat 2026-10-19 15:20Z in the Claude project thread (D-024).

## D-031 Target function of the Brain: find trading methods automatically and use the one with the highest expected value for the day (2026-10-19)
- OWNER statement, 2026-10-19 15:54Z: "こういうった手法を自動でさがして当日最も期待値のある手法で売買するのがブレインに求めている機能".
- Meaning, as Claude records it (the GPT lead owns the architecture):
  - The Brain keeps a library of candidate methods (for example opening-range breakout, pullback buy) and their measured results, split by market condition (market mood, semiconductor strength, daily trend stage).
  - Each morning it classifies the day's condition and picks the method with the highest expected value for that condition, only where enough past samples exist.
  - Methods are searched and re-scored automatically, with out-of-sample checks (first half and second half, walk-forward). The number of variants tried is recorded to limit overfitting.
- Unchanged constraints: real_submit_allowed=false. Until a separate OWNER decision, the Brain proposes and the OWNER decides each trade. Data for automatic search must be licensed for that use (MS2 data on the OWNER PC, subject to its terms; TradingView data is not used for machine search).
- The Claude Brain track (D-030) is the manual first step: candidate methods are tested in TradingView by the OWNER.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: OWNER chat 2026-10-19 15:54Z in the Claude project thread (D-024).

> D-032 and D-033 are recorded on Issue #282 only (D-032 is reserved for the v3 watch universe; D-033 was allocated earlier). They are not synced in this file yet. This edit adds D-034 to D-042 and does not renumber or overwrite any earlier decision.

## D-034 R2 "地合い弱い" is the VWAP breadth already in the Collector (documentation correction, 2026-10-22)
- R2 "地合い弱い" means: among eligible names with fresh, valid VWAP data (and an adequate sample count), 40% or fewer trade ABOVE their VWAP. This is the definition already in the Collector code.
- It does NOT mean "40% or fewer names advancing versus the previous close". Any description saying so is wrong and is corrected here.
- Why: the R2 backtest matched the Collector's recorded "地合い弱い" label, so its numbers hold only for this definition. Changing the definition would make R2 an untested rule.
- The R2 formula, threshold and backtest labels are unchanged. The OWNER left the choice to the AIs ("R2はAIが決めて判断する").
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: GPT lead record on Issue #282, comment 6335516423 (COORD-V10-POSTCLOSE-AUDIT-DECISIONS-20261022-01), P0-V10-POSTCLOSE-AUDIT-AND-DECISIONS-20261022.

## D-035 OWNER-approved draft repair scope on the 08c1479 line (2026-10-22)
- On the development line (PR #488, HEAD 08c1479), the Claude on the OWNER PC may draft these fixes only:
  1. Gateway 28581 cache: run git once at start-up, reload large files only when they change, and fail closed if the cache is invalid.
  2. Remove the browser speech in `opportunity_radar.js` and in the KIOXIA tab.
  3. Show `ev_pct` as the expected value and `score_pct` only as 「順位スコア」.
  4. Exclude time after 15:30 JST from the virtual-downtime metric, without changing any timestamp or stop log.
  5. S1-S3, D-023 Excel order:
     - START refuses if another Excel exists.
     - STOP checks for another Excel before stopping anything.
     - STOP never quits an Excel instance that still holds other workbooks.
- No safety gate is loosened. Nothing is deployed until an independent audit and a separate OWNER approval.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: GPT lead record on Issue #282, comment 6335516423 (COORD-V10-POSTCLOSE-AUDIT-DECISIONS-20261022-01), P0-V10-POSTCLOSE-AUDIT-AND-DECISIONS-20261022.

## D-036 GPT API input cap of 24,000 bytes (2026-10-22)
- The OWNER approved 24,000 bytes as the upper bound for the input of each existing specialist GPT API run, including feedback and metadata.
- It is a byte limit, not a token allowance. It does not approve external JPX figures, extra cost, more runs or new paid calls. Other budget limits are unchanged.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: GPT lead record on Issue #282, comment 6335516423 (COORD-V10-POSTCLOSE-AUDIT-DECISIONS-20261022-01), P0-V10-POSTCLOSE-AUDIT-AND-DECISIONS-20261022.

## D-037 JPX all-issue margin data is read locally by the Brain on the OWNER PC (2026-10-22)
- The Brain on the OWNER PC may read JPX all-issue margin balances locally, with source and as-of date validated.
- This is not the JPX daily designated-issue list.
- Official figures are not sent automatically to the paid GPT API, to the cloud or to GitHub. Licence and machine-reuse permission remain separate gates.
- The current 7-day age limit is not approved as a trading freshness rule. A later freshness decision is required.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: GPT lead record on Issue #282, comment 6335516423 (COORD-V10-POSTCLOSE-AUDIT-DECISIONS-20261022-01), P0-V10-POSTCLOSE-AUDIT-AND-DECISIONS-20261022.

## D-038 Research-only HMAC subkeys for feedback (2026-10-22)
- Records the PR #488 research-only scheme: context-labelled HMAC-SHA256 subkeys derived from the existing bridge key, one for feedback and one for read receipts. The Brain-only receiver ACK key stays separate.
- Approved for isolated synthetic review and documentation only. It is not evidence of separate trust boundaries and does not authorize production keys or rotation.
- No secret values in the public repo. Production security review and OWNER approval remain required.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: GPT lead record on Issue #282, comment 6335516423 (COORD-V10-POSTCLOSE-AUDIT-DECISIONS-20261022-01), P0-V10-POSTCLOSE-AUDIT-AND-DECISIONS-20261022.

## D-039 Voice alerts are limited to rules ①②④⑤ and IR急騰 (2026-10-22)
- The only allowed voice alert categories are the signal rules ①②④⑤ and IR急騰.
- Browser narration of current price / VWAP and the KIOXIA tab voice are removed.
- No new voice categories, no change to colours, fonts or the fixed zaraba layout, and no link to orders.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: GPT lead record on Issue #282, comment 6335516423 (COORD-V10-POSTCLOSE-AUDIT-DECISIONS-20261022-01), P0-V10-POSTCLOSE-AUDIT-AND-DECISIONS-20261022.

## D-040 Whole-screen LIVE gate: design only, no relaxation (2026-10-22)
- Today one missing name keeps the whole screen from showing LIVE. The current gate is NOT relaxed.
- Future design: separate Collector/market health from per-symbol FRESH / STALE / UNKNOWN / INVALID, with explicit partial coverage. A missing or stale name can be unavailable on its own while other safely sourced data stays visible as RESEARCH / PARTIAL, never as global LIVE.
- Aligned with D-026, with fail-closed negative tests. Any runtime threshold change needs independent acceptance and explicit OWNER approval.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: GPT lead record on Issue #282, comment 6335516423 (COORD-V10-POSTCLOSE-AUDIT-DECISIONS-20261022-01), P0-V10-POSTCLOSE-AUDIT-AND-DECISIONS-20261022.

## D-041 Paid GPT API ledger: no new paid runs until the reset gap is fixed (2026-10-22)
- The audit found the paid ledger can be reset by pointing environment settings at a new registry or ledger. That is not accepted.
- No NEW billable API runs until fixed. Prerequisites:
  - a protected, non-resettable lifetime spend record;
  - an approval that is not just an environment flag;
  - reconciliation against the provider's usage records;
  - a verified provider-side hard limit where available.
- The existing $1 per run, $8 lifetime reservation and no-retry rules stay.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: GPT lead record on Issue #282, comment 6335516423 (COORD-V10-POSTCLOSE-AUDIT-DECISIONS-20261022-01), P0-V10-POSTCLOSE-AUDIT-AND-DECISIONS-20261022.

## D-042 Stale and empty tabs: design only (2026-10-22)
- Hide stale/static displays and unimplemented empty tabs from active trading navigation when they cannot show source and as-of time. Keep the evidence and code history.
- Rebuild only functions with rights-cleared current sources and verified use.
- The fixed intraday zaraba screen, its order, palette and fonts stay. No unapproved tab redesign or deletion of valid live widgets.
- A per-screen cleanup table is to be submitted before any change.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: GPT lead record on Issue #282, comment 6335516423 (COORD-V10-POSTCLOSE-AUDIT-DECISIONS-20261022-01), P0-V10-POSTCLOSE-AUDIT-AND-DECISIONS-20261022.

## D-023 interpretation for S1-S3 (2026-10-22)
- The Controller refuses to launch if another Excel workbook or process exists.
- STOP checks for another Excel before stopping any V10 process or quitting Excel.
- If another Excel cannot be proven absent, normal STOP refuses safely and reports BLOCKED. It never closes another file.
- Emergency procedures beyond D-023 need a separate OWNER decision.
Source: GPT lead record on Issue #282, comment 6335516423 (COORD-V10-POSTCLOSE-AUDIT-DECISIONS-20261022-01), P0-V10-POSTCLOSE-AUDIT-AND-DECISIONS-20261022.

## D-043 One versioned mandatory checklist for the supply/SQ analyst (2026-10-22)
- Every supply/SQ analyst run reads the full checklist (C01-C10), with its version and hash, and reports each item as VERIFIED / UNVERIFIED / STALE / NOT_APPLICABLE. A missing item marks the report QUALITY_INCOMPLETE. Unknown values are never filled in by guessing.
- Items:
  - C01 market-wide margin balances, ratio and margin unrealized P/L, with the weekly change;
  - C02 liquidation/relief-selling hypotheses with falsifiers;
  - C03 per-symbol margin;
  - C04 short-sale ratio, lending and reverse interest;
  - C05 foreign investor and arbitrage flows;
  - C06 futures/options and SQ calendar;
  - C07 sector rotation;
  - C08 source, as_of, available_at and data rights;
  - C09 review of previous hypotheses;
  - C10 three-line next-session warning, with no trade decision.
- Market-wide margin risk is reported separately from the technical R2 label (D-034). Neither changes the other.
- OWNER-only market figures stay on the PC (D-037) and are never posted to Issue #282, GitHub or social media.
- The checklist must fit inside the 24,000-byte input cap (D-036). On overflow, the run is blocked, never truncated. No paid API run under D-041.
- Wiring the checklist into the API prompt is assigned to the PC Claude after a separate authorization. Checklist changes need a numbered OWNER decision (D-024). The planned file `docs/analysts/SUPPLY_SQ_REQUIRED_CHECKLIST_V1.md` is not committed yet.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: Issue #282 comments 6336507382 and 6336655933.

## D-044 Market regime / observed algorithm-behaviour research subsystem (2026-10-22)
- Adopted as P1 research. It classifies the morning's market type from observable prices. It does NOT identify who is trading or which execution algorithm runs. Labels:
  - VWAP_PERSISTENT_SELL / VWAP_PERSISTENT_BUY
  - FUTURES_LEAD_TREND_CANDIDATE
  - INDEX_LINKED_SYNCHRONOUS_CANDIDATE
  - VWAP_RANGE
  - MIXED / UNKNOWN
- Each label carries its evidence, confidence and falsifiers. It gives no buy/sell advice and places no order.
- Labels are frozen at 09:15 and/or 09:30 JST, using only data available by then, and are then checked against the rest of the day. A whole-day tag made afterwards is kept separate and is never a live label.
- Validation:
  - chronological train / validation / holdout days;
  - every tried combination counted;
  - net of costs and slippage;
  - compared with the unchanged R2;
  - exits of 15/30/60/90/120 minutes and the close studied as research only.
  - Too few days gives INSUFFICIENT_SAMPLE.
- The R2 definition (D-034) and its 60-minute maximum hold are unchanged.
- Order splitting is not inferred from the four recent trade prints. Futures lead/lag stays UNKNOWN without licensed, synchronized timestamps.
- Roles:
  - the PC Claude makes a read-only inventory of logs since 2026-09-19 and builds the isolated offline classifier and backtest;
  - the cloud Claude does the independent review on sanitized fixtures;
  - the GPT lead owns the contract and acceptance.
- Phases:
  - 0 data inventory;
  - 1 offline classifier and backtest;
  - 2 independent review;
  - 3 research SHADOW (separate OWNER authorization);
  - 4 Brain input, then UI/voice only after OWNER acceptance.
- The D-035 fixes come first for production. No change to the running V10, Excel, paid API, schedules, UI colours/fonts or real orders.
State: PENDING_DOC_SYNC until merged to `main` (D-022).
Source: Issue #282 comment 6336857406.
