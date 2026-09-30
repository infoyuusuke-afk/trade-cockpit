# NEXT5 discovery preparation — DO NOT MERGE / DO NOT DEPLOY

Issue #284 / Draft PR #283. Pure discovery adapter; no runtime integration,
network requests, polling, watchlist writes, audio, orders or MS2 subscriptions.

`discoverFromFiles({sourcePath, fixed100Path})` accepts explicit paths only.
The source contract matches `scripts/tradingview_screener_watch.py`:
`schema_version=tradingview-screener-watch-1.0`, exact source identity,
`error=null`, `updated_at`, and `scan_rows` containing `code`, `exchange=TSE`,
numeric `change_pct` and `relative_volume`. Rankings are deliberately not
merged: the same security legitimately appears in several ranking lists.
Use the unique `scan_rows`; duplicate identities block the entire snapshot.

The existing producer queries Japan with volume > 1,000,000, capped at 300
rows. This is broader than fixed100, **not exhaustive market coverage**, and
does not prove surge onset. No new ranking weights or buy/sell conditions.
All valid outside-fixed100 records are retained in source order.

Acquisition `updated_at` supports the producer's explicit `YYYY-MM-DD HH:mm:ss
JST` format and second-resolution ISO `+09:00`. Original text is retained.
Invalid calendar/timezone, different JST date, future time, age > 60 seconds,
source/schema/error mismatch, missing metrics, or duplicate identity block.
Acquisition freshness does not establish per-symbol quote freshness.

Fixed100 membership is recomputed from the supplied `stocks.*.ticker`
manifest, not external `already_watched`. Missing/empty/invalid/duplicate
manifest blocks; 1–100 valid entries are allowed for the existing watchlist.
Caller must supply the proven operational manifest at future integration;
this adapter cannot authenticate file provenance from a source label alone.
TSE code maps explicitly to `code.T`; raw `TSE:code` remains source identity.
This mapping is not MS2 identity verification.

The file entry point caps **each input at 5 MiB**, checking both initial size
and bytes actually read. The existing selective reader and whole-file caps
are not relaxed. File/parse/validation failure returns BLOCK and empty rows.
The pure normalizer throws a coded Next5BlockError on invalid input.

Every accepted candidate is DISCOVERY_ONLY, `ms2_verified=false`,
`ready_eligible=false`, `quote_valid=false`, `real_submit_allowed=false`.
No external price/volume/quote_time or supplied READY/MS2 flag is propagated.
`ready_candidates` is always empty, including empty valid snapshots.
The prep reader also rejects discovery-tagged records even if callers add
quote fields or set `ms2_verified=true`.

There is intentionally **no promotion API** in this P0 preparation. A later
separate trusted MS2 verifier must prove ticker identity, fresh per-symbol
quote_time, quote_valid and actual price/volume, and produce a separate MS2
quote record. A boolean from a screener can never constitute that proof.

Validation: `node --test tests/next5-selective-reader.test.cjs tests/next5-discovery.test.cjs`.
Synthetic fixtures only. Existing saved screener data is historical, not live.
No production acceptance, 28585 connection, or READY claim is made here.
