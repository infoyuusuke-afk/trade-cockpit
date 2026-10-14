# MS2 records — extraction & research-use contract v1 (Issue #376)

**OFFLINE DRAFT ONLY.** No actual MS2/Excel/OWNER PC access, no live Collector/Watcher changes, no private uploads, no main merge, no real orders. Starting main SHA: d7e884fe9f641282701cd9d01381b38825672de5.

## Verified source code, unverified machine

Main's ms2_live/MS2_RSS_100_Collector.ps1 writes under its script-relative records/YYYY-MM-DD directory, with configured IntervalSeconds=2 and SnapshotSeconds=10 (settings, not observed timing/SLA). It reads the market via Excel RSS, outputs five primary CSVs plus optional other files. A ticker's tick capture looks at four visible tick slots and suppresses a repeated ticker/exchange_time/price key for 30 minutes. Therefore the tick CSV is NOT an exchange trade tape. It has no individual executed volume/trade ID; direction_estimate is quote-based, and captured_at is a local naive timestamp, NOT proven exchange time or available_at.

Local anonymous one-day counts supplied by OWNER: ticks 159169; market_snapshots 69973; condition_log 69973; under_over 69973; trade_signals 78 **physical data lines**. Physical lines ≠ executions, unique samples, verified market observations or fills. Equal file counts ≠ a one-to-one poll join. Collector's exact installed code SHA on OWNER machine is unknown. A separate history folder was observed, but its schema/provenance is NOT VERIFIED.

## Input source contracts and prohibitions

| Source | Research-use candidate only (after further gates) | NOT evidence of |
|---|---|---|
| ticks.csv | sampled prices and estimated quote-side movement | complete tape, per-tick quantity, confirmed aggressor, fills |
| market_snapshots.csv | price, volume field, VWAP, bid/ask, best quotes and OVER/UNDER | atomic board depth 10, exchange ordering, as-of availability |
| condition_log.csv | historical OR5/OR15, EMA, flow, derived strategy condition | raw independent observations, no-lookahead proof |
| under_over.csv | displayed quote-pressure candidates | executed buying/selling |
| trade_signals.csv | signal/strategy/entry/stop/target hypotheses | actual order or trade, cost, EV, PF, DD |

Full exact ordered headers are pinned in scripts/ms2_records_quality.py. Derived and raw fields are not joined unless source timing and correspondence can be verified. No later value is backfilled as a historically available feature.

## Offline parser contract

The independent module parses ONLY five fixed filenames under an explicitly provided date-named directory YYYY-MM-DD. It never recurses, discovers arbitrary files, writes to disk, connects to a network, accesses MS2/Excel, or emits sensitive raw data. It streams UTF-8/BOM CSV, checks exact header order, record shape, captured local date/time, per-symbol local-time reversal, numeric finiteness/non-negativity, positive required price, exchange-time format, size and row caps (512MiB/2m rows per file), and source-file identity stability. It counts repeated tick keys as **ambiguous**, never as definite duplicates or lost trades. A read-time metadata change or malformed data causes BLOCKED. Missing numeric values are never inferred as zero.

Output contains only fixed file labels, aggregate counts, reason codes and explicit research status. It excludes original symbols, prices, quantities, original rows, paths, hashes, credentials and account numbers. Parser exit 0 means **Q1_PARSED_ONLY** (syntactic checks) and NEVER Q2 source authenticated, Q3 PIT research eligible, Q4 Shadow Forward eligible or Q5 performance eligible. Exit 2 indicates incomplete/blocked. This is not a security guarantee against adversarial TOCTOU or a proof that the producer is stopped; private read requires further OWNER consent and a stable closed source.

## Strategy data-use map

- DAYTRADE / OR5 / OR15 / VWAP / UP-DOWN-RANGE regimes / quote pressure: existing snapshots/condition/under_over are potential hypothesis data **only** after Q2/Q3 evidence, observed gaps, source timing and safe joins. Tick data cannot evaluate fills.
- Earnings pre-run-up, earnings-through, earnings-post: require time-versioned official earnings events, original publication timestamps, old analyst forecasts, guidance and gap market outcomes. No historical lookahead permitted.
- 2x/10x growth: requires as-of financials, valuations, capital changes and delisted universe. Multiple upside scenarios with explicit disconfirmation, not guaranteed returns.
- Futures/SQ hedge: requires separate dated contracts, expiry, SQ values, margin, basis, portfolio beta and costs. Stock records alone cannot prove futures hedge effectiveness.
- Global capital flow: requires independently timestamped global/sector/public flow inputs, no causal claim from price correlation alone.
- AI Strategy Evolution: hypotheses → offline research → out-of-sample replay → Shadow Forward → promotion candidate, all behind independent data/Risk/Permission gates.

## Acceptance and next milestone

Current phase: synthetic-only Windows and Linux tests on exact PR HEAD, source-only Draft PR; no actual private user CSV is read. After separate explicit OWNER approval, inspect private files locally while the Collector is stopped and files are stable, output anonymous quality metrics only. Then separately establish producer-code/source authenticity, source timestamp precision, per-symbol gap/coverage, volume semantics, and PIT join identity. The next phase is scenario research only after quality gates. No strategy promotion or orders.

Mandatory safety values: real_submit_allowed=false, promotion_eligible=false, statistical_edge_confirmed=false; eligible observed N=0, EV/PF/DD and verified realized profits UNKNOWN. Do not alter existing canonical/hash semantics, history, Collector/Watcher, live trading or 14-stacked IPC Draft PRs.