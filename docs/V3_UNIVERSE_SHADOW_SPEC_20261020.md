# Universe v3 — offline Shadow selection pilot (2026-10-20)

PROJECT_ITEM_ID: P0-V3-PURPOSE_BASED_UNIVERSE_SHADOW-20261020
OWNER authorization: 2026-10-20, purpose-based surveillance replaces the fixed-100-as-goal assumption.
Status: DRAFT_ONLY; NOT_CONNECTED; NO_RUNTIME_CHANGE; NOT_ACCEPTED_FOR_PRODUCTION.
Implementer: GPT development lead (isolated offline pilot). Independent acceptance: progress coordinator/Claude.

## Decision-number conflict — do not silently reassign
OWNER requested **D-024** for v3. Existing unmerged canonical-ledger Draft PR #443
already assigns D-024 to the instruction-recording rule and records D-025 through D-031.
Issue #282 comment 6286617491 additionally refers to a different reported D-024.
Therefore D-024 is **CONFLICTED** and v3 is **PENDING_CANONICAL_NUMBER_RECONCILIATION**.
PR #443's document owner must reconcile the numbering, with coordinator and OWNER
approval, before editing docs/DECISIONS.md or merging. This branch does not create
another DECISIONS.md or overwrite PR #443.

## OWNER-approved targets (not rigid RSS limits)
A Market regime: Nikkei 225, TOPIX, Growth 250, Nikkei VI, futures, NT ratio,
  17 sector representatives; roughly 25 logical instruments.
B OWNER charts: up to **8** liquid names; morning refresh; tape + 10-deep board
  is a future runtime requirement, NOT implemented here.
C Brain liquidity universe: 30–40 candidates from trading-value leaders, weekly review.
D PRE-NEXT/supply/GPT/Claude: 5–8 names, morning review before 08:45 JST.
E Discovery: market rankings + short availability and credit supply. Discovery
  remains OUTSIDE the MS2 RSS watch rows; promoting into B/D requires provenance
  and separate approval. The existing Yahoo auto-scraper is NOT approved.

A+B+C+D arithmetic gives 68–81 logical assignments before overlap. 60–75 is a
planning range, NOT an invariant. De-duplicate by instrument_id, retain all role
memberships, report the actual count and avoid assuming RSS formula capacity.

## Scope / non-goals
- Shadow *selection* and after-the-fact observation only; no stock picking/scores
  tuned to future returns; no real order, simulated order fill, or P&L claim.
- No edits to existing Excel, V10 Controller, watchlist_100.json, index.html,
  existing Brain, existing Shadow supervisor ledger, CI workflows or schedules.
- No new network access, broker access, Yahoo HTML fetch, scraper, external bill,
  runtime switch, protected main update or auto merge.
- No live event propagation. The exported snapshot is observation-only.
- Data files remain ONLY in local private storage **outside the Git repository**.
  No actual symbols, raw board, price, holdings or local paths are committed.
- 'MS2_LOCAL' input is gated by a rights_verified boolean furnished by the local
  operator. It is an input attestation, NOT independent licensing verification.
- A snapshot with missing or future information is rejected, never backfilled.

## Input and outcomes
CLI: python scripts/v3_universe_shadow.py --input PRIVATE_INPUT.json --output PRIVATE_OUTPUT.json
Optional: --outcomes PRIVATE_OUTCOMES.json (retrospective observation only).
No default input or output. External synchronization must NOT be inferred.

Input schema v3-universe-input-1:
{
 "schema_version": "v3-universe-input-1",
 "selection_at": "2026-10-20T08:40:00+09:00",
 "input_source": "SYNTHETIC" | "MS2_LOCAL",
 "rights_verified": true | false,
 "session_id": "opaque-local-session",
 "rows": [{
   "instrument_id": "symbol-or-index-code", "instrument_type": "EQUITY|INDEX|FUTURE|SECTOR_PROXY",
   "roles": ["A","B"], "selected": true|false,
   "observed_at": "ISO offset", "available_at": "ISO offset",
   "prior_day_trading_value_yen": int|null,
   "spread_bps": number|null, "bid_depth_yen": int|null, "ask_depth_yen": int|null
 }]
}
All rows must be known by selection_at. A previous-day total must be explicitly
available by selection time; **same-day end-of-day trading value is not usable in
a morning selection**. Role ceilings A<=25, B<=8, C<=40, D<=8; no fixed 100
count and no requirement to fill every allocation in the prototype. Non-equities
are role A only.

Output is a NEW, exclusive private immutable snapshot file per run, containing
selection digest, source, timing, row count, roles, the OWNER's provisional
**1% of prior-day trading value** notional *screening cap* if the datum exists,
and whether spread/depth evidence is present. A liquidity cap is NOT an executable
risk limit, and fill/cost feasibility is UNKNOWN. Multiple roles on one instrument
consume one unique slot. No trading decision is emitted.

Optional forward outcomes:
{"schema_version":"v3-universe-outcomes-1","rows":[{
  "instrument_id":"...", "horizon_end_at":"ISO offset",
  "available_at":"ISO offset", "return_pct":number
}]}
Outcomes must end AFTER selection and be available no earlier than horizon end;
they cannot affect selection. This computes only observed mean/absolute returns
in the selected and nonselected cohorts and explicit coverage, **not EV,
net P/L, fill expectancy, or strategy profitability**. Missing outcomes stay
MISSING/UNKNOWN, never zero. The nonselected cohort must be separately sourced
from an authorized breadth feed before capture-rate claims.

## Source rights and test boundaries
Official Yahoo! Finance support says automated scraping is prohibited:
https://support.yahoo-net.jp/SccFinance/s/article/H000011276
Therefore scripts/market_ranking_watch.py MUST NOT be automatically invoked
for v3 Shadow, until an explicitly authorized replacement is accepted.
For index/derivatives, Rakuten's official MS2 RSS help lists instrument codes
and distinct RssMarketHeader / RssFOPMarket functions:
https://marketspeed.jp/ms2_rss/onlinehelp/ohm_002/ohm_002_07.html
https://marketspeed.jp/ms2_rss/onlinehelp/ohm_002/ohm_002_03.html
Official documentation is only capability evidence; no successful OWNER-PC RSS
subscription has been proven. Human-only third-party displays do not confer AI
processing rights. A source-by-source license review remains mandatory.

## Acceptance gates (pilot)
1. Synthetic tests reject missing rights, naive/future times, duplicate symbols,
   non-equity B/C/D, and B>8/C>40/D>8.
2. Check that instrument role overlaps count once and that 1% is computed
   using only already-known *prior-day* data. Missing turnover remains UNKNOWN.
3. Forward outcomes cannot contaminate selection; missing unselected data
   remains MISSING with separate denominator.
4. Private file already present is never overwritten; no output below repo root.
   Written snapshot is independently re-read and digest-checked.
5. No existing CI, Excel, V10, or real-submit settings are touched.
6. Independent Windows synthetic validation and OWNER-PC data-source entitlement
   review are PENDING. Do not claim this pilot is collecting live data.

## Next approved implementation sequence
- P0-a: v3 synthetic offline Shadow (this Draft); independent test review.
- P0-b: existing freshness ①/② plus restart-surviving private logs & readback;
  quote change and Collector heartbeat are distinct; only verified per-symbol
  input may enter model results.
- P0-c: rights-cleared discovery universe, PIT candidate scoring and weekly
  validation against selected/unselected, net-of-cost Shadow backtesting.
- P0-d: V10 RSS row count, role-based slot assignment and B/D morning switches,
  after pin/Excel/Controller safety design and separate OWNER runtime approval.
- P0-e: real-data Windows acceptance. real_submit_allowed=false at every phase.

Economics: actual sales/realized P&L/costs/net project profit/100B remaining UNKNOWN.
