# Research candidate adapter — design (no implementation yet)

PROJECT_ITEM_ID: `P0-RESEARCH-CANDIDATE-ADAPTER-DESIGN-20261020`
Owner of this design: Claude (PC). Compatibility spec and acceptance: GPT development lead.
Independent audit: coordinator. Status: DESIGN ONLY. No runtime, Shadow ledger, manifest pin,
approval rule or safety gate change. `real_submit_allowed=false`.

## Purpose
Score the candidates of every brain (GPT Brain observations, Claude Brain rules, PRE-NEXT and
supply/demand analyst scenarios) with the **same evaluation logic** as
`scripts/v10_brain_virtual_outcome_audit.py`, side by side, **without writing to or mixing with**
the existing `ai-shadow-supervisor-1` ledger.

## Hard boundaries
1. The existing Shadow `ledger.jsonl` is never written, appended, re-sequenced or renamed.
2. Research candidates live in their own private file family (`research_candidates.jsonl` →
   `research_outcomes.jsonl`) with their own schema `research-candidate-ledger-1`.
3. Read-only inputs only: Claude Brain signal output, analyst scenario records, and the AI Cockpit
   MS2 records (`market_snapshots.csv`) for pricing. No Excel, MS2, network, broker or order access.
4. Outcomes are VIRTUAL (published price, no fills, no costs): `costs_verified=false`,
   `broker_fills_verified=false`, `tested_expectancy_available=false`, `promotion_eligible=false`.
5. No market values, tickers or paths in public outputs (aggregate stats only, as the existing audit).

## Candidate record (`research-candidate-ledger-1`)
| field | rule |
|---|---|
| `seq` | 1..N, strictly increasing within the file; a reset starts a new file |
| `source` | one of `GPT_BRAIN`, `CLAUDE_BRAIN`, `PRE_NEXT`, `SUPPLY_DEMAND` |
| `strategy` | source-defined id (safe string as in the existing audit) |
| `ticker`, `side` | `^[A-Z0-9]{4}\.T$`, `LONG`/`SHORT` |
| `published_at` | ISO with offset; time the candidate became available (never back-dated) |
| `trigger` / `invalidation` | machine-checkable conditions (price, time window) or `null` |
| `entry_rule` | e.g. `NEXT_PRICE_AFTER_TRIGGER`; entry price is taken from MS2 records at/after trigger |
| `stop_price` or `stop_pct` | required; geometry checked like the existing audit |
| `exit_rule` | e.g. `TIME 15:20`, `STOP`, `TARGET` |
| `evidence_ref` | opaque id of the analyst report / Claude Brain output (no text, no URL) |

Rules: a candidate published after its trigger time is `LOOKAHEAD_REJECTED`; duplicate
(source, ticker, side, trigger window) is `DUPLICATE_REJECTED`; untriggered candidates are kept as
`NOT_TRIGGERED` (counted for detection/miss statistics, not for R).

## Outcome evaluation
- Entry/exit prices from MS2 records with `source_timestamp_at` freshness <= 120 s (same rule as the
  existing audit); an entry/exit without a fresh price is `CONTAMINATED_BY_DATA_OUTAGE`.
- R = signed change / |entry − stop|, recomputed independently; P/L per share reconciled.
- Per source and per strategy: virtual N, win rate, mean R, R profit factor, `research_sample_n_at_least_20`,
  plus detection delay (trigger time − published time) and misses (big moves with no candidate,
  defined by a fixed rule agreed with GPT).
- The existing audit function is reused for the R statistics by feeding it converted events in a
  **separate in-memory sequence** that carries `schema_version="research-candidate-ledger-1"`;
  if the existing audit cannot accept a second schema without change, GPT decides between
  (a) a thin parallel auditor sharing the R/PF code, or (b) a schema parameter added to the auditor.

## Tests (to be written by Claude after GPT accepts the spec)
Synthetic only: look-ahead rejection, duplicate rejection, stale-price contamination, stop geometry,
untriggered handling, per-source separation, and a proof that the Shadow ledger bytes are unchanged.

## Open decisions for GPT development lead
1. Exact compatibility path (a) or (b) above.
2. The "miss" definition (e.g. a ticker moving >= X% intraday with no candidate from any source).
3. Where the private research files live on the OWNER PC.
