# Card System contract (P0-B-0)

Shared card UI for the AI Trade Cockpit, added 2026-09-25 per Owner/GPT
direction (P0-B: unify all tabs except the Kioxia prediction chart onto one
card language). This is the **foundation** pass only: `card_system.css` /
`card_system.js` exist and are loaded on every page, but no existing tab has
been migrated onto them yet — SCALP 5 / EVENT 5 / OVERNIGHT keep using
`.scalp-card` / `renderScalpCard`, MS2 LIVE TOP5 keeps `.ms2-live-card`, for
now. Migrating each tab onto this contract is P0-B-1 through P0-B-5.

## Files

- `card_system.css` — visual tokens and layout classes (`.cc-*` prefix).
- `card_system.js` — `renderCockpitCard(model)` (full card) and
  `renderCockpitWatchRow(model)` (compact horizontal row, for on-air /
  watchlist-style lists). ES module; also attaches both functions to
  `window` for the existing non-module inline scripts to call.
- `tests/card_system.test.mjs` — `node --test` coverage.
- `.github/workflows/card-system-tests.yml` — runs the above on any change
  to the two files above (mirrors `routine-bridge-tests.yml`'s pattern).

## Model shape

```js
{
  symbol: "285A",              // required. Ticker without exchange suffix.
  company: "キオクシアHD",      // optional. Falls back to symbol if absent.
  direction: "long",            // required. One of long|short|wait|block.
  directionLabel: "BUY",        // optional override of the badge text.

  price: 49870,                 // optional. Current price.
  changePct: 1.24,              // optional. Signed percent vs. prior close.

  ageSeconds: 12,               // optional. Age of the underlying data point.
  staleThresholdSeconds: 60,    // optional. Used with ageSeconds to derive
                                 // fresh/stale when `freshness` isn't given.
  freshness: "fresh",           // optional explicit override: "fresh" |
                                 // "stale" | "unknown".
  freshnessLabel: "12秒前",     // optional display text; defaults to an
                                 // auto-formatted age, or "鮮度不明".

  entry: 49870, stop: 49400, target: 50650,  // optional. Any subset shown.

  metrics: [                    // optional. Free-form label/value pairs -
    { label: "VWAP", value: "49,668" },       // VWAP / OR5 / OR15 /
    { label: "OR5", value: "49,230–49,870" }, // confidence / EV / anything
    { label: "確信度", value: "72%" },         // else with existing data all
  ],                             // go here; entries with a null/empty value
                                  // are dropped, never shown as "—" filler.

  catalyst: "決算08/07発表・PTS +4.2%",  // optional one-line catalyst/news/
                                          // earnings note.

  conflict: false,               // optional. Truthy (bool or a message
                                  // string) shows a conflict banner. Only
                                  // set this when two sources actually
                                  // disagree - never to mean "unknown".

  failClosed: false,             // optional. Truthy (bool or a message
                                  // string) switches the card to its muted
                                  // fail-closed style, replaces the badge
                                  // with "FAIL-CLOSED", and must be set
                                  // whenever the caller cannot vouch for
                                  // the data's freshness/consistency - the
                                  // renderer does not compute this itself.

  foot: "条件待ち",              // optional trailing note line.
}
```

## Rules a caller must follow

1. **Never invent a value.** If the data source doesn't have `entry`, leave
   it `null`/absent - the renderer shows the order block only when at least
   one of entry/stop/target is a finite number, and metrics entries with no
   value are filtered out rather than rendered as "—".
2. **`failClosed` is the caller's decision, not the renderer's.** The
   renderer only changes the visual style; the caller is the one who knows
   whether the upstream signal/freshness gate has failed closed. Existing
   fail-closed logic (voice timing, market-hours gates, RSS freshness
   thresholds, etc.) is not touched by this file.
3. **`conflict` means two sources disagree**, not "we don't know yet" -
   use `freshness: "unknown"` / omit `ageSeconds` for the latter.
4. Escaping is handled internally (`company`, `catalyst`, `foot`,
   `metrics[].label/value`, `freshnessLabel`, `directionLabel` are all
   HTML-escaped) - pass plain strings/numbers, not pre-escaped HTML.

## Not covered here

- Data fetching, polling, or freshness computation itself - callers compute
  `ageSeconds` (or pass a ready `freshness`) from their own existing
  timestamp/staleness logic.
- Buy/short/order execution logic - this is a display-only contract.
- Migrating any existing tab - see P0-B-1..5 in
  [AI_SHARED_SHEET.md](AI_SHARED_SHEET.md) for the planned order.
