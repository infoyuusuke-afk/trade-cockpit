# V10 Cockpit Intelligence Redesign

Status: design-only / implementation not started  
Source issue: #266  
Base: `fix/v9-ui-voice-convergence@097a29a9`

> IMPORTANT: the local V9 TEST machine contains additional unpushed hotfixes for stale-value suppression and Excel lifecycle cleanup. This branch must never be used to reset or overwrite that local checkout. Implementation must first reconcile those local fixes into Git.

## 1. Current-state findings

### CONTROL
`trade_control.js` already:
- classifies records into SCALP / EVENT / REALTIME / OVERNIGHT / SWING / VALUE / KIOXIA;
- computes count, wins, win rate, P&L, PF, average R;
- distinguishes missing history from 0 trades.

Missing:
- max drawdown;
- cumulative P&L;
- daily/weekly series;
- recent-20 trend/streak;
- MFE/MAE summary;
- strict Real vs Shadow/Paper vs Backtest lanes;
- reliable historic `cockpit_tab` tagging.

### EVENT 5
Existing overnight PTS and IR+PTS cards are currently rendered inside the MS2 live section. EVENT 5 is still a separate all-market monitor. This is the wrong ownership boundary for overnight/event escalation.

### REALTIME 5
`scripts/update.py` still emits visible `#data-quality-gate`. NEXT THEME RADAR is also emitted in the main page rather than treated as a research source.

### KIOXIA
Existing assets are strong but presentation is fragmented:
- `kioxia_prediction_history.json` has sample count, direction hit rate, MAE, analog date, similarity, predicted/actual return, path fit;
- live MS2 state already has preopen plan/score, gap, quote, imbalance, order-flow and historical prediction fields.

The redesign should primarily change orchestration/presentation and confidence calibration, not discard these assets.

### Earnings
Existing system already has:
- JPX earnings schedule ingestion;
- `earnings_expectation()`;
- `earnings-calendar.js`;
- catalyst handling;
- a 7-day TOP15 lane.

Main gap: one-month tracking, price-in analysis, historical post-earnings reaction, deeper company-level evidence and escalation into SWING monitoring.

---

## 2. Target architecture

```
RESEARCH / REFERENCE
  ├─ NEXT THEME
  ├─ news / macro / peers / supply-demand
  ├─ earnings research
  └─ PTS / disclosures
          │
          ├── qualified event handoff ──> EVENT 5
          ├── live-confirmed setup ─────> REALTIME 5
          └── pre-event swing watch ────> SWING 5

TRADE / SHADOW / BACKTEST RESULTS
          │
          └──────────────────────────────> CONTROL

KIOXIA historical + preopen + live microstructure
          │
          └──────────────────────────────> KIOXIA forecast state
```

Research discovers. Strategy tabs act. CONTROL measures. KIOXIA forecasts.

---

## 3. CONTROL data contract

New generated file: `performance_by_strategy.json`

```json
{
  "schema_version": "performance-by-strategy-1.0",
  "updated_at": "JST timestamp",
  "strategies": [
    {
      "tab": "event-hot",
      "label": "EVENT 5",
      "mode": "shadow",
      "source_status": "connected",
      "sample_count": 42,
      "wins": 25,
      "losses": 17,
      "win_rate": 59.5,
      "pnl_yen": 184000,
      "pf": 1.72,
      "avg_r": 0.31,
      "max_drawdown_yen": -62000,
      "max_drawdown_r": -3.4,
      "mfe_avg_r": 0.91,
      "mae_avg_r": -0.48,
      "current_streak": 3,
      "current_streak_type": "WIN",
      "cumulative_series": [
        {"date": "2026-09-01", "pnl_yen": 12000, "cum_pnl_yen": 12000}
      ],
      "daily_series": [
        {"date": "2026-09-01", "pnl_yen": 12000, "trades": 2}
      ],
      "recent_trades": []
    }
  ],
  "unclassified_records": 0
}
```

Rules:
- Real / Shadow / Backtest are separate strategy rows or separate filters; never aggregate by default.
- `source_status != connected` must display UNKNOWN/NOT CONNECTED, not zero.
- max drawdown is computed from closed/evaluated equity curve only.
- OPEN_MARK rows are not treated as final realized wins/losses.
- historic records without a deterministic tab tag remain unclassified until migrated.

UI:
- top summary cards;
- one cumulative P&L chart;
- one horizontal strategy comparison chart;
- strategy cards with win rate/PF/avgR/maxDD/sample;
- recent-20 strip/list;
- filter: Real / Shadow / Backtest.

---

## 4. EVENT 5 data contract and escalation

New generated file: `event_candidates.json`

```json
{
  "schema_version": "event-candidates-1.0",
  "updated_at": "JST timestamp",
  "candidates": [
    {
      "ticker": "1234.T",
      "name": "Example",
      "event_sources": ["PTS", "IR", "PREV_LIMIT_UP"],
      "pts": {
        "price": null,
        "gap_pct": null,
        "turnover_yen": null,
        "liquidity_pass": false
      },
      "previous_limit_state": "LIMIT_UP",
      "disclosure": {
        "type": "UPWARD_REVISION",
        "published_at": null,
        "source_url": null
      },
      "earnings": {
        "days_to_event": null,
        "surprise_score": null,
        "priced_in_score": null
      },
      "next_theme": {
        "theme": null,
        "score": null,
        "status": null
      },
      "live_confirmation": "NOT_STARTED",
      "expectation_score": 0,
      "evidence": [],
      "fail_closed": false
    }
  ]
}
```

Sources:
- JNX/PTS candidate feed already emitted through live MS2 JSON;
- IR+PTS candidate feed already exists;
- prior-day limit-up/down scanner must be added;
- NEXT THEME handoff codes/status must be consumed;
- earnings/revision source may enrich the score.

Suggested scoring dimensions (implementation must calibrate, not assume weights are optimal):
- event strength;
- PTS gap;
- PTS turnover/liquidity;
- prior limit state;
- disclosure strength;
- theme confirmation;
- prior-day volume anomaly;
- live/preopen confirmation.

Required badges:
`PTS`, `PREV_LIMIT_UP`, `PREV_LIMIT_DOWN`, `IR`, `EARNINGS`, `NEXT_THEME`, `MULTI_SOURCE`.

---

## 5. REALTIME 5 contract

Visible sections:
- REALTIME candidate cards only;
- opportunity/radar cards that already passed mandatory freshness/identity checks;
- live status banner.

Remove from visible REALTIME:
- `#data-quality-gate`;
- NEXT THEME RADAR;
- research-only material.

Internal gate still validates:
- market date;
- ticker/code identity;
- current data age;
- price integrity;
- required live source state;
- no stale fallback.

Failure behavior:
- withhold candidate or show explicit BLOCK;
- never expose stale current price.

---

## 6. NEXT THEME research handoff

NEXT THEME belongs to Reference/Research.

Each theme card should show:
- detected theme;
- score/status;
- evidence freshness;
- candidate stocks;
- escalation state;
- destination strategy if qualified.

Handoff rule output:
```json
{
  "code": "0000",
  "theme_id": "...",
  "research_status": "CONFIRMED",
  "handoff_target": "event-hot",
  "handoff_reason": ["fresh_catalyst", "market_reaction", "local_ms2_confirmation"]
}
```

No direct trading enable from research.

---

## 7. KIOXIA forecast state

New generated file: `kioxia_forecast_state.json`

```json
{
  "schema_version": "kioxia-forecast-state-1.0",
  "asof": "JST timestamp",
  "phase": "preopen",
  "selected_scenario": "YORITEN",
  "scenario_probabilities": [
    {"scenario": "YORITEN", "probability_pct": 62.0},
    {"scenario": "GU_CONTINUATION", "probability_pct": 24.0},
    {"scenario": "RANGE", "probability_pct": 14.0}
  ],
  "confidence_pct": 62.0,
  "confidence_status": "CALIBRATED",
  "sample_n": 38,
  "calibration_window": "last_120_sessions",
  "historical_hit_rate_pct": 63.2,
  "next_horizon": "5m",
  "next_direction": "DOWN",
  "next_path": "VWAP_RETEST",
  "inputs": {
    "market_regime": null,
    "preopen_gap_pct": null,
    "preopen_imbalance_pct": null,
    "flow_bias": null,
    "or5_state": null,
    "vwap_state": null
  },
  "evidence": [],
  "fail_closed": false
}
```

Scenario vocabulary should be finite and testable:
- YORITEN
- YORIZOKO
- GU_CONTINUATION
- GD_REBOUND
- RANGE
- SPECIAL_QUOTE_DELAY
- UNKNOWN

Confidence policy:
- empirical calibration only;
- sample threshold required;
- insufficient sample => `confidence_status=INSUFFICIENT_SAMPLE`, percentage omitted/null;
- show sample size and realized historical hit rate next to the forecast.

Top-of-tab UI:
1. selected scenario;
2. confidence + n;
3. next 1m/5m expected path;
4. prediction chart;
5. model performance card.

Raw metrics move below as evidence details.

---

## 8. Earnings one-month intelligence

New generated file: `earnings_watchlist.json`.

Per-company fields:
- date / days_to_event / stage;
- historical quarterly sales, operating profit, EPS;
- company guidance;
- consensus;
- revision history;
- progress rate;
- segments;
- seasonality;
- FX sensitivity;
- peer read-through;
- price run-up before earnings;
- volume/positioning context;
- historical post-earnings gap, +1d, +5d, +20d;
- surprise score;
- priced-in score;
- evidence URLs and timestamps.

Stages:
- T30
- T14
- T7
- T1
- RESULT

Calendar visual:
- earnings date colored;
- priority watched name indicator;
- stage badge;
- monitored-company count on day.

Key analytical split:
- `surprise_score`: probability/strength of fundamental beat/miss evidence;
- `priced_in_score`: amount of favorable expectation already reflected in price;
- never collapse them into one “good earnings” label.

SWING handoff:
- only candidates meeting research thresholds become swing-watch candidates;
- handoff contains evidence, not a guaranteed buy instruction.

---

## 9. File-level implementation map

Likely files to change after local-hotfix reconciliation:

- `trade_control.js`
  - consume performance_by_strategy.json
  - render charts/cards/filters
- `scripts/update.py`
  - generate performance/event/earnings contracts
  - move PTS/IR ownership to EVENT 5
  - remove visible quality gate
  - restructure tab HTML
  - generate Kioxia forecast state
- `index.html`
  - generated output; do not hand-edit independently from generator except during controlled V9 hotfix reconciliation
- `earnings-calendar.js`
  - colored dates, days-to-event, stage/priority, detail cards
- `next-theme-radar.js`
  - research lane + handoff status
- `card_system.js`
  - reuse cards; stale-price suppression from local V9 must be preserved
- tests
  - new structural contract tests
  - performance math tests
  - event handoff tests
  - confidence calibration tests
  - earnings stage tests
  - desktop/mobile visual tests

Potential new generators/modules:
- `scripts/performance_dashboard.py`
- `scripts/event_candidates.py`
- `scripts/kioxia_forecast.py`
- `scripts/earnings_intelligence.py`

Prefer modules over making `scripts/update.py` even larger.

---

## 10. Acceptance tests to implement

### CONTROL
- missing history != 0 trades;
- OPEN_MARK excluded from realized result metrics;
- maxDD math fixture;
- Real/Shadow/Backtest never aggregate by default;
- every displayed strategy has deterministic tab mapping or UNKNOWN.

### EVENT 5
- PTS candidate appears in EVENT 5, not REALTIME 5;
- previous limit-up/down badges survive rendering;
- NEXT THEME never escalates without required evidence;
- stale PTS candidate is fail-closed.

### REALTIME 5
- no visible `data-quality-gate`;
- no NEXT THEME section;
- stale candidate never shows a current price.

### KIOXIA
- no confidence percentage with insufficient sample;
- probability sum validation;
- selected scenario exists in scenario list;
- displayed sample/hit rate agree with history file;
- forecast result summary updates only from evaluated records.

### Earnings
- calendar earnings dates visibly marked;
- T30/T14/T7/T1 stage transitions deterministic;
- surprise and priced-in scores displayed separately;
- stale/unavailable evidence is labeled;
- no 7-day-only restriction in research tracking.

### Regression
- V9 fail-closed;
- local stale-value suppression preserved after reconciliation;
- Excel close leaves EXCEL.EXE=0;
- V9 state removed after clean close;
- 28580/81/82/83 offline after clean close;
- MS2 tab survives reopen;
- desktop/mobile visual smoke remains green.

---

## 11. Delivery sequence

1. Capture/reconcile locally tested V9 hotfixes into Git.
2. Rebase this design onto that reconciled V9 head.
3. Implement performance data pipeline + CONTROL.
4. Implement EVENT routing / prior-limit scanner / research handoff.
5. Remove REALTIME research/quality clutter.
6. Implement KIOXIA forecast-state orchestration/calibration.
7. Implement earnings T30 intelligence.
8. Upgrade Reference/Research cards.
9. Full regression + visual acceptance.
10. Only then consider merge/deployment.
