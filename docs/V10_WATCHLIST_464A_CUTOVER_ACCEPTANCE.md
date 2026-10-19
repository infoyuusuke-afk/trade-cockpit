# V10 watchlist 5595.T → 464A.T: cutover acceptance

PROJECT_ITEM_ID: P0-V10-WATCHLIST-464A-SOURCE-PIN-20261019
State: synthetic CI only. Windows real-machine acceptance NOT_RUN. Not cut over. real_submit_allowed=false.

## Why

QPS研究所 (5595) was delisted on 2025-11-27. QPSホールディングス (464A, TSE Growth) listed on 2025-12-01 by a 1:1 share transfer. MarketSpeed II RSS returns empty values for 5595.T, so the Collector dropped watchlist slot #88 and V10 ran at 99/100. The OWNER approved the replacement on 2026-10-19. The D-number for this decision is pending (D-022 procedure); proposed next free number: D-027.

## What changes together

Both must switch in the same stopped window. Switching only one gives a sheet-code mismatch (ROW_SHEET_CODE_MISMATCH / WRONG_SYMBOL_MAPPING) and V10 fails closed.

1. `ms2_live/watchlist_100.json`, slot #88: `QPS研究所（5595）`/`5595.T` → `QPSホールディングス（464A）`/`464A.T`, deployed by the approved V10 RUN from the pinned source (manifest blob `ecff9eed20478bfe2b74b68dbbcf1cbc811fba38`).
2. The OWNER workbook `Kioxia_MS2_RSS_Live_Signals.xlsx`: in sheet `100銘柄RSS`, row 89 (code cell and every `RssMarket` formula), and in sheet `KIOXIA_JNX`, every `5595.T` becomes `464A.T`. The name `QPS研究所（5595）` becomes `QPSホールディングス（464A）`. Nothing else changes.

## Preconditions (all required)

- A V10 source pin approved by the OWNER for a HEAD that contains this watchlist (no self-generated pin).
- V10 stopped (STOP of the running version); no `EXCEL.EXE` running; ports 28580-28584 free.
- A backup of the current workbook, plus a record of its SHA-256 before the swap.
- The prepared workbook passes the read-only check against the exact watchlist that will be deployed:
  `python scripts/verify_v10_workbook_watchlist.py <copy-of-prepared.xlsx> ms2_live/watchlist_100.json --forbid 5595.T` → `"result": "PASS"` (exit 0).

## Cutover steps (OWNER PC, outside market hours)

1. Run STOP for the running V10 version and confirm that V10 processes, Excel and ports are gone.
2. Back up the workbook and record its SHA-256.
3. Replace the workbook with the prepared one and record its SHA-256.
4. Run the verifier on a copy of the installed workbook against the watchlist of the approved HEAD. It must PASS.
5. Start the approved V10 version. The bundle preflight and RUN deploy the pinned watchlist.
6. Read-only checks after start:
   - `/health` and `live_ms2.json` show slot #88 as `464A.T`;
   - the universe counts 100 declared and 100 rows once 464A has traded;
   - there is no `WRONG_SYMBOL_MAPPING` or `ROW_SHEET_CODE_MISMATCH`;
   - real_submit_allowed is false.

## Rollback

1. Run STOP for the V10 version.
2. Restore the backed-up workbook and check that its SHA-256 equals the recorded pre-swap value.
3. Start the previous V10 version. Its own watchlist still has 5595.T, so the workbook and the list match again: the 99/100 state, which is known and fail-closed for slot #88.
4. Never mix a new workbook with an old list, or an old workbook with a new list.

## Evidence prepared on 2026-10-19 (OWNER PC, read-only, nothing installed)

- Pre-swap backup SHA-256 matches the installed workbook (untouched).
- The prepared workbook differs from the original only in the four XML parts that hold 5595.T and the name. Replacing back gives byte-identical parts; the other 15 parts are identical.
- Verifier results:
  - prepared workbook vs the #451 watchlist: PASS (100/100, order kept, row 89 `464A.T`, KIOXIA_JNX 16× `464A.T`, no `5595.T`);
  - installed workbook vs the #451 watchlist: FAIL, row 89 (expected until cutover);
  - prepared workbook vs the old watchlist: FAIL, row 89. This is why the two must switch together.
