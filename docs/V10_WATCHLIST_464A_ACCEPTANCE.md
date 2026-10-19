# V10 watchlist 464A: simultaneous switch acceptance (D-027)

PROJECT_ITEM_ID: P0-V10-WATCHLIST-464A-SOURCE-PIN-20261019
State: READY_FOR_ACCEPTANCE (synthetic CI PASS). Real machine NOT_RUN. Not deployed.
real_submit_allowed=false throughout.

## What changes together

| Side | Before | After |
|---|---|---|
| `ms2_live/watchlist_100.json` (pinned in the V10 manifest) | `QPS研究所（5595）` / `5595.T` | `QPSホールディングス（464A）` / `464A.T` |
| OWNER workbook, 100-symbol RSS sheet, the matching row | `5595.T` in the code cell and RSS formulas | `464A.T` |
| OWNER workbook, any other sheet holding the old code (KIOXIA_JNX) | `5595.T` | `464A.T` |

The Collector compares each row's sheet code with the watchlist ticker. If only one side changes, that row reports `ROW_SHEET_CODE_MISMATCH`, the board is incomplete, and V10 stays fail-closed. That is the safe failure, but the switch must be made on both sides at once.

The runtime takes the watchlist from its pinned source. Editing the watchlist of an installed runtime by hand breaks its hash pin and is not allowed. The new list reaches the PC only with a runtime built from a source that carries it (#451 or a later accepted HEAD).

## Pre-switch checks (read-only, PC)

Each check must be PASS before the switch. A check that cannot be run is NOT_RUN, never PASS.

1. A backup of the current workbook exists. Record its SHA-256 and confirm it opens.
2. Record the SHA-256 of the prepared workbook, and confirm the workbook opens without repair.
3. On the 100-symbol RSS sheet, the matching row has `464A.T` in the code cell and in every RSS formula on that row, with no `5595` left. Every other row is identical to the backup.
4. KIOXIA_JNX has no `5595` left. Every other cell is identical to the backup.
5. The prepared workbook's code column holds exactly 100 codes. The order equals the watchlist order, and there are no duplicates.
6. The 100 sheet codes equal the 100 tickers of `ms2_live/watchlist_100.json` at the runtime HEAD, in the same order.
7. Rollback is ready: the previous runtime and the backup workbook can be restored together (below).

## Switch (only after OWNER approval of the runtime HEAD)

1. Market closed, V10 stopped (STOP confirms no workers and no ports). No other Excel open (D-023).
2. Install the approved runtime HEAD that carries the new watchlist, following the normal source-pin procedure.
3. Replace the workbook with the prepared one.
4. Start V10. Acceptance:
   - Universe verified, 100/100.
   - No `ROW_SHEET_CODE_MISMATCH`.
   - The new row has a dated quote during market hours, or is reported missing and fail-closed outside them.
   - Shadow only.

## Rollback

1. STOP V10.
2. Restore the backup workbook and the previous runtime together.
3. Start, and confirm the previous behaviour (99/100, fail-closed on the old row).

Never roll back only one side.

## Evidence so far (synthetic)

- PR #451 HEAD e208c6eb2f7209f4e4870a2b18c265ad698c3f61: watchlist blob `ecff9eed20478bfe2b74b68dbbcf1cbc811fba38` equals the manifest pin. Synthetic CI 9/9 SUCCESS.
- `scripts/ci_v10_watchlist_replacement.py` and `tests/test_v10_watchlist_replacement.py` reject each of the following:
  - 99 or 101 entries
  - two changes
  - a duplicate ticker
  - a reorder
  - an unapproved code or name
  - an attribute change
  - the unchanged list
  - a manifest pin mismatch
- Codes with a letter are already exercised by the V10 synthetic suites (identity `285A.T`), and the Collector's code pattern accepts `[0-9]{3}[A-Z]`.
