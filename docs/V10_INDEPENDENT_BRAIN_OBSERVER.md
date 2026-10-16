# V10 independent BRAIN observation engine: scope and acceptance

## Real process topology
- Controller ports 28581/28584 both run AI_COCKPIT_GATEWAY_V10.ps1. Neither is a BRAIN engine.
- Existing Python ai_shadow_supervisor.py is a separate virtual-observation supervisor, NOT BRAIN.
- New Python scripts/ai_brain_observer.py is a third, independently owned process. V10 Controller starts it with --live <RuntimeDir>/live_ms2.json and --status <RuntimeDir>/ai_brain_observer_status_v1.json. It restarts at most five times with bounded delays; owner PID is recorded in V10_CONTROLLER_STATE.json and included in owner-identity-controlled stop.
- Only reads the local existing Collector JSON, never CSV, Excel COM, broker, positions, accounts or credentials.

## Read-only observation semantics
- For source-qualified snapshots with >=90 canonical distinct symbol rows, valid workbook and process counts, explicit offset timestamp <=60 seconds, matching file mtime, source not stale/conflicted, compute coarse OR15+VWAP side-of-range WATCH counts and up to five symbol-only observations.
- No BUY/SELL order, fill assumptions, strategy PF, or expected winrate is claimed; this is merely deterministic real-data processing.
- MS2 source_timestamp in existing Collector is usually time-of-day only (e.g., 09:19:58). No independently verified exchange date exists. Therefore last_market_data_at stays null and exchange_tick_date_verified=false even when snapshot publication is fresh. source_authenticated=false, cross_source_join_allowed=false, promotion_eligible=false, eligible_observed_n=0 and real_submit_allowed=false by construction.
- Input unverified => BRAIN BLOCKED, no watch observations.

## Gateway & UI
- Gateway /health only reads the private BRAIN file, validates schema, Controller-owned process identity, published PID, timestamp + file freshness, unsafe-evidence claims and safe counts. It surfaces coarse state and count, never full raw rows.
- UI distinguishes "independent BRAIN observer published" from verified market-tick freshness or a validated profitable trading engine; 28584 remains a second Gateway.
- All tests are synthetic unless OWNER PC acceptance explicitly confirms real MS2 runtime. No branch merge/deployment done.

## Remaining blockers
Actual Windows MS2 integration acceptance, full four-source independent dated market-tick receipts, old September 25 historical dashboard replacement, real-candidate PF validation, real net-profit measurement. Never promote real trading from this observation-only feature.
