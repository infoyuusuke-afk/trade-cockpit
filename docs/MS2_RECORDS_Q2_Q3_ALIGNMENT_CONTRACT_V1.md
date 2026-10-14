# Issue #376 / Phase Q2-Q3 — MS2 records attribution and temporal-join analysis v1

Status: DRAFT, offline and synthetic only; no OWNER Windows private datasets inspected. Base: Draft PR #377 (Q1 MS2 records contract); main reviewed SHA d7e884fe9f641282701cd9d01381b38825672de5.

## Hard evidence from the main Collector

ms2_live/MS2_RSS_100_Collector.ps1 sequentially writes three CSV rows per symbol on a due snapshot in this order: condition_log.csv, under_over.csv, market_snapshots.csv. It uses the local $now string at second resolution for captured_at. There is no embedded poll ID, writer transaction ID, session nonce, producer code version, captured/available timestamp pair, or atomic cross-file transaction. Another branch writes trade_signals.csv on strategy-specific conditions, not under the same unconditional 3-file writer. Ticks come from four visible cells, with ticker+exchange_time+price deduplication. Data correctness cannot be proven by equal row counts.

## Observable candidate matching (not guaranteed correspondence)

The offline analyzer reads the existing Q1 five-file validator first. Only when all five Q1 checks pass, it reads exactly four files again (snapshots, conditions, under_over, trade_signals), from a single explicitly provided YYYY-MM-DD folder. It counts ephemeral (ticker,captured_at) tuples in memory only, reports:

- distinct keys appearing exactly once in EACH of the three snapshot-derived files;
- keys present more than once in one of the streams (ambiguous);
- keys missing from one or more streams, including per-stream counts;
- signals with zero, exactly one, or multiple snapshot-key candidates; repeated signal keys;
- aggregate reason codes and record counts.

**Same timestamp and ticker are only a candidate key, NOT evidence of a shared atomic poll or no-lookahead causal linkage.** Equal file counts do not qualify a join. There is no nearest-time or prior-day carry forward; any missing match stays missing. Output never includes ticker, price, row, exact timestamp, original path or raw hash. Privacy data are not transmitted. All outputs have source_attribution=UNVERIFIED, poll_join_proven=false, decision_asof_proven=false, pit_research_eligible=false, eligible_observed_n=0. CLI exit code 2 is intentional even when candidate alignment metrics are computed.

The code repeats stability checking on the second pass (file stat and open file identity). This is insufficient to prove global atomic snapshot, absence of an adversarial race, or stoppage of Collector. No raw data or live trading should use it until a distinct OWNER-approved local check.

## Requirements for genuine Q2 source attribution

- Independent proof of original Producer script file and code SHA at capture time, plus session ID and executable launch configuration; a current SHA alone does not prove historical capture provenance.
- Per-source observation method, RSS field/version, local PC wall-clock synchronization, timezone and resolution; no guessing.
- Private local immutable manifest linking raw file digest, timestamp, Collector session and producer version. Do not publish raw hash or full PC path to public GitHub.
- Actual coverage, restart boundaries, missing reads, invalid source values and write-failure intervals. Missing true exchange ticks cannot be reconstructed from top-four displayed trade cells.

## Requirements for genuine Q3 point-in-time suitability

- Per-poll unique session+poll identifier (symbol scoped where needed) present in all derived streams.
- Per-poll source acquisition start/end, accepted/enqueued/persisted timestamps, earliest available_at; condition signal generated-at and its source observation references.
- Timestamps with explicit offset and precision. Local captured_at from old records is naive and does not attest availability or exchange sequencing.
- Proven feature dependencies; no using after-decision market/earnings data. For old CSV without these fields, leave status historical exploratory/UNKNOWN, do not fabricate a link.
- Explicit gap/staleness/duplicates and fail-closed conflicting evidence, append-only history. Security and privacy boundaries preserved.

## Minimal decision about business value

MS2 snapshots/conditions/under_over may support hypothesis discovery about OR5/OR15, VWAP, UP/DOWN/RANGE regimes and quote-pressure after Q2/Q3 evidence is independently verified. Legacy trade_signals are not fills and cannot compute real EV. Earnings run-up/earnings hold, multi-baggers, and futures/SQ hedge require separate point-in-time event/fundamental/futures source contracts. Research pipeline must never promote Q1 data automatically to Shadow or execution.

## Acceptance / non-authorization

Windows/Linux synthetic negative tests required for matching/unmatched/duplicate/time reversal/malformed data, repeated signal key, stale file identity and private no-output. Run exact-HEAD CI and record failures, never change prior canonical/hash/history or MSC Watcher/Collector. Real private original review or Collector runtime modification is separately OWNER-approved. Draft PR is not a merge permit. real_submit_allowed=false; promotion_eligible=false; statistical_edge_confirmed=false. Real eligible N=0, EV/PF/DD UNKNOWN.
