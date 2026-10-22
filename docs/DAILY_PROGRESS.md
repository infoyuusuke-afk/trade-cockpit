# 100億PROJECT — DAILY PROGRESS
Newest first. Keep one short entry per day; detailed evidence stays in PRs and the Issue #282 records.

## 2026-10-22 JST

### 0. 現実の紙幣
- 今日の現実売上：未確認
- 今日の実現トレード利益：未確認
- 今日の実費：未集計
- 今日のOwner労務コスト：未集計
- 今日のProject純損益：未確定
- 100億円までの残額：UNKNOWN

### 1. Decisions (Issue #282 comment 6335516423, PENDING_DOC_SYNC)
- R2 "地合い弱い" stays the Collector's VWAP breadth; the "advancers" wording was wrong (D-034).
- OWNER-approved draft repair scope on the 08c1479 line (D-035).
- GPT API input cap 24,000 bytes (D-036). JPX all-issue margin data is read locally by the Brain (D-037). Research-only HMAC subkeys (D-038).
- Voice alerts limited to rules ①②④⑤ and IR急騰 (D-039).
- Design only, no change now: whole-screen LIVE gate (D-040), stale and empty tabs (D-042).
- No new paid GPT API runs until the ledger reset gap is fixed (D-041).

### 2. Work
- Claude independent defect audit after the close, of live 48bbfe2 and dev 08c1479. Read-only; nothing was changed on the running V10.
  - Serious: slow Gateway 28581 replies against the screen timeout; browser speech left over; one missing name blocks screen LIVE; screen shows the ranking score as 期待値.
  - Safety: no real-order path, no committed secrets, no freshness-gate loosening since 714c020. S1-S3 (Excel handling vs D-023) and S4 (paid ledger reset) found.
- Repairs under D-035 are being drafted on the OWNER PC. Not deployed; independent audit and OWNER approval are still needed.

### 3. Blockers
- New paid GPT API runs are on hold (D-041).
- Gateway speed during market hours is not measured yet.

## 2026-10-18 JST

### 0. 現実の紙幣
- 今日の現実売上：未確認
- 今日の実現トレード利益：未確認
- 今日の実費：未集計
- 今日のOwner労務コスト：未集計
- 今日のProject純損益：未確定
- 100億円までの残額：UNKNOWN

### 1. Decisions
- V10 target frozen: AI-max automation with OWNER final approval (D-020).
- Data rights policy frozen (D-019).
- V10 roadmap G0–G6 frozen (D-018).
- One AI per PR (D-017).
- V10 localhost security is release-blocking P0 (D-021).
- V10 runs with no other Excel in use; Controller and Safe Stop refuse with a clear reason (D-023).
- OWNER instructions take effect for AIs only once recorded as a D-number (D-024).
- 2026-10-19: the trial of unaccepted PR #446 was a one-time OWNER exception, not an acceptance (D-025).
- 2026-10-19: V10 market operability follows staged plan C; plan A first, watchlist replacement waits for the OWNER (D-026).
- 2026-10-19: OWNER approved replacing one delisted watchlist code with its successor listing; Draft PR #451, synthetic CI PASS, real machine NOT_RUN (D-027).
- 2026-10-19: OWNER retired the pre-#446 V10 and approved a trial of the fixed #446 line on the OWNER PC (Shadow only); not an acceptance (D-028).
- 2026-10-19: Specialist-to-coordinator round trip on Issue #282 verified interactively for Revenue Hunter, PRE-NEXT and supply/SQ. Specialists now report on scheduled runs, and the coordinator ACKs (D-029). Scheduled E2E not yet observed. Compat reader: Draft PR #455.

### 2. Work (all Draft; nothing merged; no real-machine action)
- PR #441: V10 localhost security fix (GPT).
  - Claude independent audit (OWNER-directed) of old HEAD 1eb6dd5: CONDITIONAL PASS with 3 findings.
  - GPT fixed all 3 in the same PR. New HEAD 44f417a: Windows/Ubuntu synthetic CI 9/9 PASS.
  - Independent re-audit of the new HEAD pending. Draft, unmerged, not verified on OWNER Windows.
- PR #442: synthetic AI candidate → simulated OWNER approval → Shadow E2E (GPT). CI PASS. Paper-only: no authenticated phone, no actual Shadow fill, no real order.
- PR #440 independent audit (Claude, OWNER-directed): FAIL on the security P0 findings that led to #441.
- PR #439 substitute report (Claude): PARTIAL.
- PR #434 legacy V8/V9 test split: CI green. Merge awaits approval.
- PR #435 P0-14 BRAIN exact-argv tests: synthetic Windows CI 19/19.
- Canonical ledger unification: Draft PR #443 prepared, pending merge.

### 3. Blockers
- P0-27 real-machine acceptance BLOCKED at ADMISSION. Next is Issue #408 (P0-28, non-stopping diagnosis).
- No OWNER device authentication exists for approvals.
- GPT Work usage limits slow development. OWNER is considering a plan change; the cost is an OWNER decision.

## 2026-10-08 JST (carried from the V10 branch line)

### 0. 現実の紙幣
- 今日の現実売上：0円 confirmed
- 今日の実現トレード利益：0円 confirmed in current project accounting
- 今日の実費：未集計
- 今日のOwner労務コスト：未集計
- 累計Project売上：0円 confirmed

### 1. Completed
- V10 STOP acceptance PASS (as recorded then; later P0-27 shows real-machine acceptance is not complete)
- GitHub legacy pre-V10 cleanup
- Local runtime folder cleanup PASS

### 2. Discovery
EVENT 5 / HOT is not yet true full-market real-time detection.
