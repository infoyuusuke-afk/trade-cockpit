# V10 Brain virtual-outcome audit — research-only gate

PROJECT_ITEM_ID: `P0-V10-BRAIN-VIRTUAL-OUTCOME-AUDIT-20261019`  
Target: stacked Draft PR on #458 → #457 → #456 → #446 → #444; no production change.

## Why this exists

The currently implemented V10 `ai_brain_observer.py` is an OR15/VWAP observation engine, not a validated autonomous trading brain. The existing `ai_shadow_supervisor.py` generates local **virtual** entries/exits from Collector-published prices without quantities or independently witnessed fills. Treating these as actual profit or as the #458 observed-PAPER contract would be false.

This module adds a **read-only research audit** of the private `ledger.jsonl` written by that Shadow supervisor. It allows preliminary strategy diagnostics while making all profitability, fill and deployment gates explicitly false. It is not a route to execute trades.

## Accepted input

- An explicit, owner-controlled, non-symlinked local file named `ledger.jsonl`, at most 12 MB.
- The **complete** sequential `ai-shadow-supervisor-1` observation ledger, starting at sequence 1, with explicit offset timestamps and source pricing `collector_published_price_not_fill_model`.
- Virtual entry must carry its own fresh (<= 120 sec) dated `source_timestamp_at`, positive entry/stop with correct LONG/SHORT geometry.
- Virtual exit must match prior entry's sequence, ticker, side and strategy and agree with independently recomputed P/L **per share** and R. Any missing/malformed/future/out-of-order input blocks the whole ledger.
- Only records labeled `clean_strategy` count in grouped diagnostics; `contaminated_by_data_outage` are separated; unclosed virtual observations do not count as wins/losses.

**Not supported:** partial source files, multiple independent files with reset sequence, files written concurrently, simulated fills, broker fills, real money, costs, slippage, EV promotion, and private-data publication.

## Output and safety

CLI, for approved local data only:

`python -m scripts.v10_brain_virtual_outcome_audit --ledger <private-local-ledger.jsonl>`

Output is JSON containing only aggregate counts and per-strategy *virtual* N, win-rate, mean-R and R profit factor. No symbol, prices, positions, trades, accounts or file paths are exposed. `tested_expectancy_available=false`, `broker_fills_verified=false`, `costs_verified=false`, `promotion_eligible=false`, `real_submit_allowed=false` are fixed. These are **not validated live expectancy**.

Local reader does not modify any file, start services, connect to external networks, use Excel/MS2, publish results, or enable order routes. The existing UI palette/fonts/layout and the 31 pinned V10 runtime sources are unchanged.

## Gates for next steps

1. Independent test and review of the exact PR head and Ubuntu/Windows CI.
2. OWNER Windows private-data readback to confirm actual ledger format, date freshness and consistent source; **NOT_RUN** now.
3. Keep separate from #458's observed PAPER projection, which requires independently witnessed entry/exit fills and verified costs.
4. Attach independently observed cost/slippage and Shadow forward evidence before any EV/promotion discussion; trades do not become eligible merely from virtual R statistics.
5. Broker real-submit remains disabled; any future live authorization requires separate OWNER approval and risk/permission validation.

No budget, credential, automation, deployment, cutover or merge changes are included.
