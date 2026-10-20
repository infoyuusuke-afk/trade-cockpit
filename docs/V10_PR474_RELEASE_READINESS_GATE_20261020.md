# V10 PR #474 — OWNER decision package / release gate (2026-10-20 JST)

**Scope:** 100億PROJECT. Source and operational acceptance, not a trading authorization.  
**Status:** **DRAFT / RELEASE_BLOCKED**. Never infer live readiness from CI or a local HTML preview.  
**Review target:** https://github.com/infoyuusuke-afk/trade-cockpit/pull/474 (compare to `main`; resolve the **current HEAD** immediately before independent review).  
**Default safety:** `real_submit_allowed=false`, no live RssOrder/broker orders, no real hedge, no automated merge/deploy, no schedule mutation.

## What is now implemented

- Consolidated V10 UI Draft review for [PR #471](https://github.com/infoyuusuke-afk/trade-cockpit/pull/471) generated HTML preservation, [PR #472](https://github.com/infoyuusuke-afk/trade-cockpit/pull/472) Brain/evidence/stale banner, and PR #474 owner FOCUS / PRE-NEXT / Journal / exact blob pins. PR #474's **base is main** for single end-to-end review; older Draft PRs remain unmerged as the patch history.
- OWNER-fixed FOCUS: user adds/removes up to five codes. No automatic slot rotation. A canonical local MS2 data-source/Collector identity/evidence must be present before displaying a price; null/stale/invalid/future quotes and real-order permission mismatch BLOCK.
- **No-event failure:** after 12 seconds without a fresh `ms2RssUpdate`, FOCUS revokes visible prices; independent `paint()` check protects against throttled timer callbacks. OWNER watchlist persists.
- **Global provenance banner:** no unconditional LIVE or a nonexistent `source_authenticated=true` assertion. The actual Collector supplies `live_price_diagnostics.workbook_identity_verified`; only explicitly coherent identity/source/transport/freshness proof can show `OBSERVATION_ONLY`. After 12 seconds with no event, BLOCK. This is **source-observation eligibility**, never exchange-tick authentication or authorization to trade.
- Static top header and footer now explicitly label the dated **2026-09-25 reference**; a historical snapshot must not appear as today's morning update. Other archived sector/ranking cards remain reference-only until separately connected with certified `available_at` evidence.
- Existing fonts, palette and layout primitives are retained. No UI changes to MS2 Collector, Writer, workbook, Gateway, broker API, schedule, or background tasks.
- 31 asset source SHA records stay strict. Only the exact `index.html` asset SHA is changed, and the candidate workflow compares literal pinned hash, manifest hash and HEAD blob. Never disable `full-source-parity` or `APPROVED_FOR_RUNTIME=0`.

## Technical verification gates (DO NOT call source tests 'deployed')

| Gate | Pass evidence required | State as of package creation |
|---|---|---|
| Immutable build | Current exact candidate HEAD; 31/31 manifest asset hashes, no duplicated path, `real_submit_allowed=false`; no unreviewed changed source | GitHub source check **PASS**, OWNER previously separately checked 31/31 on older PR HEAD |
| Synthetic UI | Real inline page JS (FOCUS and global provenance) via synthetic DOM/clock, positive/negative identity, 12s no-event, navigation isolation, no stale repaint | Tested through Python/Node synthetic CI; inspect current HEAD after final commits |
| Cross-platform CI | Mobile Control, Writer Queue, Source Pin, V10 Candidate Runtime Bundle (including Ubuntu/Windows), Price Freshness (including Windows) | All must show **SUCCESS on exact HEAD**, else BLOCK |
| Independent inspection | Coordinator/reviewer confirms updated 9-file integrated source diff and no safety gate bypass at exact HEAD, GitHub evidence/ACK | **PENDING** |
| Windows static preview | Browser displays FOCUS and upper tab; add/remove with no selected symbol does not leave FOCUS; blocked quotes remain hidden | OWNER **visually observed on previous HEAD** in a read-only file preview; not evidence of current-head MS2 operations |
| Windows live observation | Separate OWNER-approved and SHA-pinned main install; single controller/Collector workbook identity; 100 symbols and quote times; per-row readback; no traffic ⇒ screen BLOCK after 12s, fresh verified reconnection ⇒ optional observation | **NOT_RUN / RELEASE_BLOCKED** |
| Safety stop & recovery | No duplicate Excel/session, state ownership, controller STOP, watcher/brain process cleanup, saved receipts; no order endpoint | **NOT_RUN** |
| Economic uplift | Timestamped forward Shadow evidence (net fees/slippage, OOS, sufficient N, risk gate); actual book P/L segregated from synthetic | **UNKNOWN** |

No file or test in this package can issue a real order.

## Owner-side state, anonymized (not a public path)

- OWNER confirmed the existing installation's source SHA and its approved-source JSON **matched an older main**; the installation was stopped and clean. Do not overwrite, migrate, or run against that installation.
- OWNER independently cloned PR #474 in an isolated local checkout at an **earlier candidate HEAD**, verified the then-current UI blob and 31/31 manifest pins with no mismatches and `real_submit_allowed=false`.
- OWNER ran only the read-only self-test (PASS; Controller started=0) and a browser `file://` visual preview. FOCUS add/remove buttons with **no selected symbol** left FOCUS active; missing MS2 data was shown BLOCKED. **No live data/communications, source authentication, new-HEAD UI verification or Windows runtime acceptance was performed.**
- Private Windows file paths, screenshot source files, local account identifiers, market feed data and other sensitive state must not be pasted into public Issue #282.

## Next actions delegated to development lead / coordinator (no OWNER prompt yet)

1. Ensure all current-HEAD 5 CI workflows (including Windows Price Freshness) pass and source/manifest strict hash parity is proven.
2. Resolve CI or source-review findings in Draft only; re-run exact-HEAD verification after every source change.
3. Get a **separate coordinator** to inspect the **integrated PR #474 against main**, plus stack ancestry / changed files, review no-event and identity proof, verify the manifest, and issue ACK with reviewed SHA in public-safe Issue #282.
4. Prepare rollout steps for an **explicitly approved** release only: new clean isolated main checkout (never modify the old running installation), controlled OWNER-approved local `V10_APPROVED_SOURCE.json` with branch `main`, full newly merged SHA and `real_submit_allowed=false`, run existing source preflight, then the original guarded one-click V10 launcher. Do not generate approval artifact in Draft.
5. On Windows run, compare real quote timestamps with trusted local readback without copying account rows to public GitHub, verify MS2 loss >12s and restoration, all screen tabs, STOP cleanup, backup/rollback. If any prerequisite fails, return BLOCK and keep old stopped system safe.

## Actual OWNER decision boundary

After independent current-HEAD review and synthetic CI **all PASS**, request one clear OWNER decision: **approve the exact reviewed source for a guarded observation-only V10 release/Windows implementation test, or reject with corrections**.

An OWNER affirmative is **not** permission for real broker orders, hedge, unlimited spend, disabling fail-closed, or automatic future promotion. A separate explicitly constrained deployment action is necessary. OWNER retains final authority; code author cannot self-approve.
