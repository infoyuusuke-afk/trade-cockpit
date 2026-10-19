# V10 UI OWNER Design Lock + Incremental Acceptance

Project: 100億PROJECT / AI Cockpit V10
Authority: OWNER direction reconfirmed 2026-10-19
Implementation line: Draft PR #456 (missing-value fail closed) → Draft PR #457 (CONTROL evidence-gated strategy performance)
Reference specification: Issue #266; verified LIVE path: Issue #251
Status: DRAFT REVIEW ONLY — not a runtime approval or Windows live acceptance.

## Immutable visual baseline

- **Preserve the current dark palette, card/background colors, rise/fall status colors, font families/sizes, and all visual states.**
- **Preserve the intraday tab arrangement and existing card positions.** No tab replacement, removal, renaming, or reordering.
- No aesthetic "modernization," recoloring, global typography, or CSS refactor without separate explicit OWNER approval.
- Existing `index.html`, `theme.css`, `card_system.css`, `card_table_adapter.css`, `focus.css` and other pinned view assets are **unchanged** in #456/#457. Their SHA parity is enforced by the source-manifest CI.
- CONTROL additions may append below existing CONTROL cards using the **existing** `card wide`, `pane-intro`, `cc-grid`, and `cc-card` classes. The intraday SCALP/EVENT/REALTIME layouts remain untouched.
- A browser rendering comparison on the Windows OWNER environment is **NOT_RUN**. Source-level UI immutability is **not** a pixel-level acceptance.

## CONTROL P0: performance evidence and modes

Display lanes independently:

| Lane | Allowed input evidence | Display |
|---|---|---|
| REAL | Authenticated broker reconciliation only, **not** `paper_trade_history.json` | **未接続／UNKNOWN** until that separate source exists |
| SHADOW/PAPER | Explicit `mode: shadow/paper`, `cockpit_tab`, unique `trade_id`, settled PnL, and dated provenance | Virtual metrics only; not realized account profit |
| BACKTEST | Explicit `mode: backtest` with the same provenance gates | Backtest metrics only; no mixing with Shadow |
| Legacy / malformed / duplicate / future | Insufficient evidence | Quarantine; never infer mode/strategy/zero |

Minimum fields for *eligible simulated performance display*:

- `trade_id`: stable nonempty, unique string for this historical feed.
- `cockpit_tab`: exact supported strategy tab, not guessed from a strategy-name substring.
- `mode`: explicit `paper`, `shadow`, or `backtest`; `real` is **not accepted** from this file.
- `closed_at`: explicit ISO-8601 timezone; settled event time.
- `available_at`: explicit ISO-8601 timezone; cannot precede `closed_at` and cannot lie in the future.
- `pnl_yen`: finite measured simulated PnL, not a missing/null/blank field.
- `status` (if present) must equal `CLOSED`; `OPEN_MARK`/未決済 is not a settled result.

Proof model: these fields make a simulated historical row **eligible for display**, not market-source authenticated or broker reconciled. Cost/slippage provenance remains unverified.

CONTROL cards append *after* prior owner/control cards and report cumulative simulated PnL, daily/weekly series (JST), win rate, PF, average R, maximum drawdown, MFE/MAE where all observations have the same unit, and the most recent 20. Ranking is only within the same simulation lane and requires **at least 20 eligible trades per strategy and two candidate strategies**. It is not an automated entry/sizing signal.

## Actual source-migration finding

Inspection of the currently published `paper_trade_history.json` in the reviewed V10 branch: 281 rows, **all** lack explicit `mode` and `cockpit_tab`; 185 lack `strategy_id`. These rows are not to be silently migrated or attributed to REALTIME 5. The current UI must report classification as UNKNOWN/quarantined, not invent a preferred strategy.

A future producer contract can provide explicit mode/tab/closed_at/available_at/trade_id with independent quality gates. That producer change requires its own source/CI review; this UI PR does not change any writer.

## Synthetic acceptance matrix

| Area | Test evidence | Required |
|---|---|---|
| Missing zero suppression | `tests/v10_trade_control_missing_data.test.mjs` | 8 negative/positive cases |
| CONTROL history provenance, chronological/replay gating, duplicate and status checks | `tests/v10_control_performance_lanes.test.mjs` | 14 synthetic cases |
| Runtime source pin | `downloads/V10_RELEASE_BUNDLE_MANIFEST.json` + existing CI | Exact Git blob SHA for `trade_control.js`; other 30 runtime assets unchanged |
| Visual lock | PR compare vs parent #456 | No `.css`, `index.html`, intraday DOM changes |
| Existing safety | HTTP/security, STOP/Controller, Gateway, Windows parse, mobile | CI must remain green |
| Windows visual match/live verification | OWNER device during scheduled acceptance | **NOT_RUN**; no deploy/merge before independent review |

## Subsequent UI work (separate, small Draft PRs)

1. CONTROL source producer: create genuine mode/strategy/provenance labels and readback, no fake historical migration.
2. EVENT 5: route PTS/IR/previous limit-up/down candidates into event lane with source/freshness, not reorder tabs.
3. REALTIME 5: keep quality checks internal but keep stale/invalid candidates withheld; NEXT THEME remains research-only.
4. KIOXIA: scenario, calibrated confidence with N, forecast-versus-actual evidence; unknown if insufficient sample.
5. Earnings: T-30/T-14/T-7/T-1 intelligence with source timestamps and no fabricated consensus.
6. Desktop/mobile visual acceptance after independent CI and source contract review.

## Safety and operational boundary

- `real_submit_allowed=false`; RssOrder/broker submit/real hedging never enabled by this UI work.
- No V10 launch, stop, restart, Excel modification, Task Scheduler change, deployment, runtime cutover, or unreviewed merge.
- No private MS2 order-book/ticks, positions, accounts, owner paths or secrets in this public document.
- Paper/backtest/Shadow statistics are not realized P&L, and no increase in EV is claimed without out-of-sample evidence.
