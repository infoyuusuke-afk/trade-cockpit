# V10 PR #474 — OWNER decision package / release gate (2026-10-20 JST)

**Scope:** 100億PROJECT. Source and operational acceptance, not a trading authorization.  
**Status:** **DRAFT / RELEASE_BLOCKED**. Never infer live readiness from CI or a local HTML preview.  
**Review target:** https://github.com/infoyuusuke-afk/trade-cockpit/pull/474 (compare to `main`; resolve the **current HEAD** immediately before independent review).  
**Default safety:** `real_submit_allowed=false`, no live RssOrder/broker orders, no real hedge, no automated merge/deploy, no schedule mutation.

## P0 browser history restore gate

A secondary no-event failure was discovered during pre-release code review: `pagehide` cleared FOCUS and global provenance watchdog timers, but returning from browser back/forward cache did not re-arm them. The corrected source registers `pageshow` for both widgets. On restore, previously accepted evidence remains BLOCKED until a new verified MS2 event; independent one-second timer is restarted, and another 12-second no-event period blocks the display again. Both real inline scripts have clock-advance/reentry negative tests in their existing Node harnesses.

## Independent coordinator P0 MODIFY — all MS2 LIVE lanes (2026-10-20)

Evidence: [Issue #282 comment #6286168929](https://github.com/infoyuusuke-afk/trade-cockpit/issues/282#issuecomment-6286168929); reviewed earlier `ccc6ea8...`, verdict **MODIFY_RELEASE_BLOCKED**. Prior HEAD is superseded; all independent review must target the current PR #474 HEAD.

**Corrective implementation, read-only UI, source-level:**
- Shared `screenReady(d)` uses explicit Collector identity and canonical local transport, `real_submit_allowed=false`, nonconflicted source, verified workbook, valid fresh offset publication within 12 seconds; `rowReady(x)` independently requires each symbol's Collector-observed quote basis/time and numeric positive price.
- The common one-second watchdog expires on 12 seconds without accepted `ms2RssUpdate`, including a successful HTTP response that repeatedly serves a frozen publication. It broadcasts a fail-closed synthetic UI event to all source consumers and clears the visible LIVE health, SCALP5, REALTIME candidates, 100-stock watchlist, preopen gap, PTS/IR cards, KIOXIA MS2 source row, historical-looking account/hold summaries and opportunity radar. A detached independent KIOXIA Watcher (port 28582) remains subject to its own existing freshness check; this change does not claim it is authenticated via port 28580.
- On `pagehide`, hidden browser tab and BFCache `pageshow`, price/display evidence is revoked until a newly verified MS2 event; timers re-arm after BFCache restore, and stale event trails cannot resurrect quotes.
- `opportunity_radar.js` uses the same source and per-ticker gate; outdated `285A.T` fixed shortlist has been updated to `464A.T` in this display module only. No changes to workbook or Collector migration.
- `tests/v10_all_live_lanes_silence.test.mjs` executes the actual screen and SCALP/watchlist/gap/KIOXIA/radar handlers with synthetic DOM+clock and confirms all lanes disable without a next event, explicit reconnect, forged/stale source, individual stale rows, and pageshow/visibility blocking. The Python/Node CI runs this test, and the legacy HTTP/200 test runner is adapted to *extract* the actual new source guard rather than implement a duplicate. Safety checks were not relaxed.
- 31-asset manifest changed exactly **two** reviewed UI sources: `index.html`, `opportunity_radar.js`; all **29 remaining** SHA pins unchanged, `real_submit_allowed=false` and `APPROVED_FOR_RUNTIME=0`.
- CI must be reverified on the latest exact HEAD. **Never promote a previous green CI run or simulated 3-hour test to Windows real-market acceptance.**

## Navigation source-of-truth reconciliation (no new OWNER tab decision)

Rechecked static `index.html`, dynamically inserted earnings tab from `earnings-calendar.js`, and the 2026-10-20 [canonical reconciliation Draft](https://github.com/infoyuusuke-afk/trade-cockpit/blob/docs/v10-ui-canonical-reconciliation-20261020/docs/V10_UI_SOURCE_RECONCILIATION_AND_OWNER_GATE_20261020.md). The 2026-10-08 sixteen-slot reference was labeled a **mock**, not an independently verified binding signed acceptance. OWNER later delegated keep/delete/refactor based on necessity (no release/merge authority).

**Current top-level actual order including the dynamic earnings insertion (14 slots):** CONTROL → BRAIN → AIトレード日記 → SCALP 5 → EVENT 5 → REALTIME 5 → PRE-NEXT → OVERNIGHT 5 → SWING 5 → VALUE 5 → FOCUS → KIOXIA → 決算日程 → 注意.

**Reference menu (nine):** 円高恩恵TOP5 / 対米投資・SMR / 主体レジーム / 検証・除外 / 相関 / 下ヒゲ / 拡大 / 大口 / 国策. The prior stand-alone weekly review remains **inside AIトレード日記**, not deleted. PRE-NEXT research remains separate from live REALTIME, and FOCUS owner-selected five are not auto-rotated.

No top-tab/button order, palette, typography, pane/score layout, scrolling behavior or dynamic earnings insertion was changed by this coordinator P0 repair. This is a code-vs-draft reconciliation, **not** a claim that every dynamic card's Windows runtime position has been visually accepted by OWNER. If OWNER later identifies a conflicting previously authorized fixed card array, retain RELEASE_BLOCKED and obtain that exact specification before changing the layout.

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
