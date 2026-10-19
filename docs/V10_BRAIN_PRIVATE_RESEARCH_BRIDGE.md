# V10 Brain Private Research Bridge — P0 evidence gate

PROJECT_ITEM_ID: P0-V10-BRAIN-PRIVATE-RESEARCH-BRIDGE-20261020
Branch target: Draft PR stacked on #459, #458, #457, #456, #446, #444.
Status: code review / synthetic CI only. No deployment, integration to the running Brain, automatic scheduling, or actual orders.

## Mission and scope

The V10 Windows MS2 Collector already produces `live_ms2.json`; the V10 AI Shadow supervisor separately appends **virtual-observation** `ledger.jsonl`. The existing Brain observer only produces OR15/VWAP watch flags. Prior PR #459 audits virtual strategy outcomes in R units but does not connect to current live-market source quality.

This bounded bridge combines the *existing independent validators* in one explicit, locally invoked one-shot:

1. Read locally observed `live_ms2.json` without modifying it. Validate stable file bytes, trusted filename, writer freshness and MS2 identity/quote provenance through `ai_shadow_supervisor.assess_live_payload`.
2. Read local `watchlist_100.json`, verify 100 unique expected tickers, require all 100 board quotes to be fresh, correctly dated, and consistent with the verified universe (`board_row_freshness` + `assess_board_availability`). **99/100 remains BLOCKED.**
3. Execute the existing OR15/VWAP Brain observer in pure read-only mode, without writing to its canonical status path.
4. Independently audit local private Shadow `ledger.jsonl` with PR #459. Contaminated, open, ambiguous or invalid data never creates profitable sample records.
5. Write only aggregate research-context JSON to the **same existing private Shadow directory as the ledger**, under a separate filename `brain_research_context_v1.json`, using an atomic private write. No fields from a raw tick/board, account, symbol, broker fill, local path, or order leave this process.

A failing/unknown input returns a durable `BLOCKED` research status, not a fabricated zero, stale last-good signal, or usable trading decision.

## Explicit local one-shot (Windows acceptance not yet executed)

Pass actual OWNER-controlled local paths; do not paste private file contents into public GitHub:

    python -m scripts.v10_brain_private_research_bridge --live <local-live_ms2.json> --watchlist <local-watchlist_100.json> --ledger <private-shadow-ledger.jsonl> --status <same-private-shadow-dir/brain_research_context_v1.json>

The bridge does **not** self-start, spawn timers, change V10 launch/stop flow, import existing runtime private data, write to any public GitHub file, communicate externally, or modify the monitored files. It is not yet a running V10 Brain consumer.

## Non-trading safety semantics

Even for a fully passing synthetic example:

- `state=RESEARCH_OBSERVATION_ONLY`, **not trade-eligible**.
- `market_data_gate=PASS` means independent timestamp/identity/100-row validation only; not cryptographic exchange-source authentication.
- `virtual_outcome_gate=PASS` means complete, internally consistent virtual observations; **not broker fills**.
- `tested_expectancy_available=false`, `source_authenticated=false`, `costs_verified=false`, `broker_fills_verified=false`, `brain_trade_decision_eligible=false`, `promotion_eligible=false`, `real_submit_allowed=false`.
- Virtual R statistics are preliminary research; no simulated vs REAL conflation, position sizing, order effects, profit or alpha assertions.
- Strategy names may be Japanese; the aggregate output is **private-local** only. Do not publish it externally without separate access/control review.

## Acceptance progression

1. Exact-head GitHub Actions Windows+Ubuntu negative tests; pin and review the base/stack. **SYNTHETIC.**
2. Compare source schema and timestamps on the OWNER Windows device in read-only operation. Do not publish local MS2/RSS data. **NOT_RUN.**
3. Independently verify persistence, restart, changes under concurrent market-data writes, quote regression over time and recovery. **NOT_RUN.** This one-shot does not assert persistent cross-run quote-regression guarantees.
4. Connect the private, non-actionable `brain_research_context_v1.json` as **read-only research input** to a distinct Brain layer only after separately reviewed integration. **NOT_RUN.**
5. Real evidence, costs, slippage, out-of-sample/Shadow forward validation and Risk/Permission/Owner gates must independently pass before any order-adjacent design. **NOT_RUN.**

This PR changes no V10 UI color, font, intraday layout, source-pin manifest or existing live Gateway/Collector/Watcher/Brain runtime. It does not modify task schedules, permission gates, purchase/paid API settings, or code for real orders.
