# AI Cockpit Master Specification v1.0

Status: DRAFT / shared source of truth for GPT + Claude + Owner  
Checkpoint main SHA: `1e856eeacdf71006fa095da27e1aa6e46862fb7b`  
Date: 2026-09-22 JST

> This document defines the target architecture, current progress, role split, safety boundaries, development plan, and autonomous-development protocol for the Japanese-equity AI Cockpit project.
>
> If this document conflicts with a newer approved GitHub Issue comment, the newer approved Issue comment wins. If source code, tests, Actions, or actual-machine evidence conflict with prose, verified implementation/evidence wins. Never infer completion from a chat summary.

---

## 1. Final objective

Build a reproducible, auditable, fail-closed AI trading cockpit for Japanese equities that connects:

- TradingView
- Rakuten Securities MARKET SPEED II (MS2) RSS
- Excel
- local Windows collectors
- GPT
- Claude / Claude Code
- GitHub / GitHub Actions

The target pipeline is:

```text
Universe discovery
  -> market data acquisition
  -> normalized point-in-time evidence
  -> asset profile / market regime
  -> strategy router
  -> scenario generation
  -> conflict resolution
  -> risk gate
  -> execution contract
  -> permission gate
  -> shadow order
  -> shadow fill model
  -> shadow position lifecycle
  -> reconciliation
  -> shadow forward evidence
  -> acceptance / calibration
  -> Owner approval
  -> future execution orchestrator
  -> optional real submit only after a separate explicit authorization
```

The design priority is not maximum short-term profit. Priority order is:

1. survive for a long time;
2. preserve capital;
3. be deterministic for the same inputs;
4. be reproducible;
5. be auditable;
6. detect stale/missing/corrupt state;
7. fail closed;
8. stop safely;
9. collect statistically valid evidence;
10. only then optimize expected value.

---

## 2. Non-negotiable safety rules

### 2.1 Real orders

Current state:

- Real submit is disabled.
- AI must not autonomously submit real orders.
- Rakuten / MS2 order functions must not be enabled without a separate explicit Owner approval.
- Existing `real_submit_allowed=false` semantics must not be weakened.

Before any future real-submit path is enabled, all of the following are mandatory:

- explicit human approval;
- maximum concurrent positions;
- maximum daily loss;
- maximum risk per trade;
- duplicate-order prevention;
- no automatic retry on UNKNOWN;
- Kill Switch;
- position reconciliation;
- broker state reconciliation;
- stale/missing data fail-closed;
- execution idempotency;
- durable audit log;
- calibration evidence;
- Shadow Forward acceptance;
- actual-machine validation.

### 2.2 Private data

Never put the following into public GitHub:

- raw MS2 board data;
- raw tape / tick data when private/local;
- account information;
- holdings;
- order details tied to the user;
- fills tied to the user;
- credentials;
- local personal paths when avoidable;
- private screenshots;
- private operational logs.

Public repository code may define contracts, validators, schemas, and sanitized evidence summaries.

### 2.3 Time semantics

All decision-relevant data must be point-in-time safe.

Forbidden:

- future data;
- lookahead;
- backfilled evidence represented as forward evidence;
- silently repaired timestamps;
- assuming timezone awareness from `tzinfo != null` alone;
- using stale last-known-good data as if current.

A timestamp is valid for the Shadow / execution stack only when timezone offset semantics are explicit and internally consistent.

### 2.4 Broken state

Never guess or repair broken state silently.

Examples:

- corrupt known-order ledger => BLOCK;
- malformed known-position identity => BLOCK;
- conflicting duplicate evidence => BLOCK;
- stale watchdog => BLOCK;
- missing required provenance => INELIGIBLE / BLOCK;
- unsupported evidence schema => fail closed.

---

## 3. Source-of-truth hierarchy

The project intentionally has several environments. They are not equivalent.

### A. GitHub `main`

The only code source of truth.

Rules:

- all durable implementation changes eventually return to GitHub;
- local-only fixes are not canonical until reconciled into GitHub;
- before starting work, fetch/pull latest main where safe;
- review the latest approved Issue comments before coding;
- do not assume an old PR still applies cleanly to current main.

### B. `C:\AI_Cockpit_OneClick_Starter`

Current deployed/runtime Windows cockpit.

Purpose:

- actual MS2/Excel operation;
- local gateway;
- local collector;
- actual-machine safety tests;
- local private evidence.

It is a deployment target, not the development source of truth.

### C. legacy local paths such as old `C:\MS2_Live\...`

Legacy / migration source only.

New development should not create another competing canonical runtime.

---

## 4. Major system layers

## 4.1 Universe / discovery layer

Inputs may include:

- TradingView scanner candidates;
- Yahoo/public market feeds;
- earnings calendar;
- TDnet/event feeds;
- predefined Japanese-equity watchlists;
- 100-stock MS2 monitoring universe;
- event/theme candidates.

Responsibilities:

- produce candidate symbols only;
- attach discovery reason and timestamp;
- never imply execution permission;
- keep unsupported/external scanner data separate from broker-grade live evidence.

Target lanes:

- SCALP
- REALTIME / DAYTRADE
- OVERNIGHT
- SWING
- LONG_CATALYST / VALUE
- TOB_MA
- SPECULATIVE_THEME / EVENT

One universal strategy must not be forced across all asset classes.

---

## 4.2 Market-data acquisition layer

### TradingView

Use cases:

- historical / Replay research;
- 15-second OHLCV research;
- Pine research;
- visual cross-check.

Rules:

- no synthetic missing bars;
- no silent resampling substitution;
- preserve observed timestamps;
- exact overlap mismatch => BLOCK;
- source mismatch => BLOCK;
- raw observed 15:25 bar or other unexpected bar must be preserved for semantics review.

Current Replay evidence:

- multiple TSE:285A 15-second exports showed exact OHLCV overlap at common timestamps;
- stitched local CORE exists outside repo;
- latest recovered CORE v2:
  - 11,605 rows;
  - first 2026-09-08 09:00:00 JST;
  - last 2026-09-18 15:30:00 JST;
  - SHA-256 `6D1821C5591E6E2D51785BE19DB20466A97D12C0613C4D0ABBAEB1C018D6BCE0`;
- source files remain local/private and are not committed.

Open semantics problem:

- an absent 15-second bucket may be an acquisition gap OR genuinely no transaction / delayed opening;
- do not classify as verified data loss without independent evidence;
- Issue #169 tracks this.

### MS2 RSS

Use cases:

- live TSE price;
- VWAP;
- board/reference fields;
- market breadth / monitoring universe;
- local tick/tape capture;
- TSE vs JNX reference separation;
- live Shadow evidence.

Rules:

- stale => unusable;
- missing => unusable;
- no fallback from JNX into TSE signal logic;
- no private runtime data in public repo.

### Excel

Excel is currently part of the MS2 RSS bridge.

Known operational lesson:

- volatile NOW() safety formulas do not self-advance without recalculation;
- a separate Heartbeat process exists;
- an independent External Watchdog exists for the Heartbeat boundary.

---

## 4.3 External Watchdog

Actual Windows cockpit acceptance for C-089 passed.

Verified behavior:

- separate watchdog process;
- duplicate start returns ALREADY_RUNNING;
- Heartbeat fresh => HEALTHY/FRESH;
- Heartbeat stopped => after configured stale threshold Watchdog becomes STOPPED/HEARTBEAT_STALE;
- consumer lease => BLOCK/WATCHDOG_STOPPED;
- fresh heartbeat required for recovery;
- official Stop verifies process exit;
- stale PID cleanup works;
- PID identity mismatch refuses to kill unrelated process;
- runtime JSON/PID files are gitignored;
- no broker/order path touched.

Autostart activation remains a separate Owner gate.

---

## 4.4 Data normalization / provenance

Every strategy-relevant record should eventually carry enough provenance to answer:

- source;
- symbol;
- venue;
- timeframe;
- observed_at;
- source timestamp;
- ingestion timestamp;
- session date;
- timezone;
- freshness;
- source version;
- strategy version;
- schema version.

No downstream component should have to infer missing provenance.

---

## 4.5 Asset profile

Strategies must branch by instrument characteristics.

Initial profiles:

- HIGH_VOL_HIGH_TURNOVER
- LARGE_GROWTH_SEMI
- LARGE_VALUE
- SMALL_GROWTH
- SPECULATIVE_THEME
- TOB_EVENT

Profile features should include at least:

- market cap bucket;
- turnover / liquidity;
- price band;
- ATR%;
- RVOL;
- gap size;
- volume shape;
- short interest / borrow availability where valid;
- sector;
- event flags.

---

## 4.6 Market regime

Do not treat the same setup identically under every market condition.

Target regime fields include:

- UP
- DOWN
- RANGE
- HIGH_VOL
- RATE_SHOCK
- POLICY_EVENT
- EVENT_LOCK
- UNKNOWN
- semiconductor strength
- breadth
- futures/sector context

UNKNOWN must not be promoted into a confident directional regime.

---

## 4.7 Strategy Router

The Router selects strategies by:

```text
asset profile
x market regime
x horizon
x time window
x liquidity / volatility bucket
x evidence quality
```

It should not output a single global BUY/SHORT answer.

One symbol may simultaneously be:

- DAYTRADE: LONG candidate
- OVERNIGHT: WAIT
- SWING: WATCH
- LONG_CATALYST: READY

Target output per strategy:

- strategy_id;
- strategy_version;
- horizon;
- side;
- status;
- trigger;
- invalidation;
- stop;
- targets;
- evidence refs;
- current-condition score;
- historical EV statistics;
- sample size;
- confidence interval;
- research / shadow / live status.

Important: current-condition score is not expected value.

---

## 4.7.1 AI Strategy Supervisor Layer / AI戦略統括層

The cockpit shall have an explicit multi-supervisor architecture above individual strategy modules and below Owner approval.

The purpose is not to let an LLM bypass deterministic controls. The purpose is to separate domain responsibility, keep strategy reasoning auditable, and present a coherent real-time advisory view.

### Supervisors / 統括者

| English | 日本語 | Primary responsibility |
|---|---|---|
| Chief AI Strategy Supervisor | 総合AI戦略統括 | Aggregate lane outputs, surface conflicts, produce the final advisory strategy view |
| Data Quality Supervisor | データ品質統括 | Freshness, source integrity, missing/stale/conflicting evidence, point-in-time checks |
| Market Regime Supervisor | 地合い・レジーム統括 | UP/DOWN/RANGE/HIGH_VOL/RATE_SHOCK/EVENT_LOCK/UNKNOWN state |
| Global Macro Supervisor | グローバルマクロ統括 | Rates, yield curves, FX, commodities, volatility and global risk context as regime modifiers |
| SCALP Supervisor | スキャル戦略統括 | Seconds-to-minutes OR5/VWAP/EMA/flow/tape scenarios |
| Event Supervisor | イベント戦略統括 | Theme/material/TDnet/earnings/sudden-volume event lane |
| Realtime Daytrade Supervisor | リアルタイム・デイトレ戦略統括 | Minutes-to-hours intraday candidate management |
| Overnight Supervisor | オーバーナイト戦略統括 | Close-to-next-open scenarios and gap risk |
| Swing Supervisor | スイング戦略統括 | Multi-day/multi-week trend/catalyst scenarios |
| Value / Long Catalyst Supervisor | バリュー・中長期カタリスト統括 | Earnings, revisions, valuation, capital return, long-horizon catalyst |
| TOB / M&A Supervisor | TOB・M&A統括 | Event-specific takeover / merger scenarios |
| KIOXIA Dedicated Supervisor | キオクシア専任統括 | 285A dedicated OR/VWAP/flow/time-of-day/deep-dive logic |
| Risk & Safety Supervisor | リスク・安全統括 | Risk Gate, stale/missing state, kill conditions, exposure constraints |
| Shadow Execution Supervisor | シャドー執行統括 | Shadow order/fill/position lifecycle only |
| Reconciliation Supervisor | 照合統括 | Intent/order/fill/position/evidence consistency |
| Calibration Supervisor | キャリブレーション統括 | Fill-model error, execution evidence, evidence sufficiency |
| Journal / Content Export Supervisor | 日記・コンテンツ出力統括 | Export only sanitized events to the separate AI Trading Journal system |

A supervisor is a logical responsibility boundary. It may be implemented by deterministic code, an LLM-assisted reviewer, or both.

### Hard boundary: deterministic core vs AI commentary

For every supervisor:

1. deterministic facts/state are authoritative;
2. LLM/AI text may summarize, compare, explain, and propose;
3. AI commentary may not mutate canonical hashes, Risk Gate, Permission Gate, Shadow state, reconciliation state, or broker state;
4. AI commentary is never a direct order-submit command;
5. unavailable LLM service must not stop the deterministic safety layer;
6. stale/missing/conflicting evidence forces WAIT_DATA/BLOCK/UNKNOWN as appropriate.

---

## 4.7.2 AI Strategy LIVE / リアルタイムAI戦略LIVE

The cockpit shall expose a dedicated real-time advisory surface:

**AI Strategy LIVE / AI戦略LIVE**

This surface aggregates the latest supervisor snapshots without becoming an execution bypass.

### Required per-supervisor snapshot

Each supervisor shall emit a point-in-time snapshot containing at least:

- supervisor_id;
- supervisor_version;
- strategy_id / strategy_version where applicable;
- symbol / universe;
- horizon;
- observed_at;
- generated_at;
- data_freshness;
- source/provenance references;
- regime;
- advisory direction: LONG / SHORT / NEUTRAL / WAIT;
- state: ACTIVE / WATCH / WAIT_DATA / BLOCK / CLOSED / UNKNOWN;
- trigger conditions;
- invalidation conditions;
- stop/target proposal when defined;
- current-condition score;
- historical EV statistics where available;
- N / sample sufficiency;
- evidence_quality;
- conflict flags;
- risk-gate status;
- shadow-execution status;
- explanatory commentary;
- real_submit_allowed = false.

### LIVE aggregation flow

```text
MS2 / TradingView / public event feeds
        |
        v
Data Quality Supervisor
        |
        +--> Global Macro Supervisor
        |          |
        |          +--> Yield Curve Engine
        |          +--> FX / Commodities / Volatility context
        |          |
        +--> Market Regime Supervisor
        |
        +--> SCALP Supervisor
        +--> EVENT Supervisor
        +--> REALTIME Daytrade Supervisor
        +--> OVERNIGHT Supervisor
        +--> SWING Supervisor
        +--> VALUE / Long Catalyst Supervisor
        +--> TOB / M&A Supervisor
        +--> KIOXIA Dedicated Supervisor
                    |
                    v
          Chief AI Strategy Supervisor
                    |
             Conflict Resolver
                    |
          Risk & Safety Supervisor
                    |
          AI Strategy LIVE display
                    |
                    +--> Shadow Execution only
                    |
                    +--> sanitized Journal Event Export
```

### Chief AI Strategy Supervisor / 総合AI戦略統括

The Chief supervisor must not simply majority-vote.

It must preserve lane independence and show, for example:

- SCALP: LONG candidate
- REALTIME: WATCH
- OVERNIGHT: BLOCK
- SWING: LONG WATCH
- VALUE: NEUTRAL

for the same symbol when that is what the evidence supports.

Its responsibilities:

- combine supervisor snapshots;
- identify cross-horizon agreement/disagreement;
- call Conflict Resolver when deterministic rules apply;
- surface unresolved conflict rather than invent a consensus;
- expose why a lane is blocked;
- distinguish current-condition strength from historical expected value;
- provide Owner-facing summary;
- never authorize real submit.

### AI Strategy LIVE UI / AI戦略LIVE画面

Minimum display:

- current JST timestamp;
- source freshness;
- Data Quality state;
- Market Regime;
- one card per supervisor/lane;
- symbol;
- direction/state;
- trigger;
- invalidation;
- Entry/Stop/Target proposal when available;
- OR5/OR15/VWAP/EMA/Flow/Volume where relevant;
- current-condition score;
- historical EV / PF / DD / N when statistically available;
- conflict state;
- Risk Gate state;
- Shadow state;
- last-update age;
- voice-alert state.

The UI must visibly distinguish:

- observed data;
- deterministic derived state;
- statistical evidence;
- AI-generated commentary.

Never label a current heuristic score as EV.

### Real-time update policy

The LIVE system should be event-driven where possible and polling-based where necessary.

Target behavior:

- MS2 facts update on local collector cadence;
- supervisor snapshots recompute only from fresh input;
- a new input event can invalidate an older advisory immediately;
- stale threshold expiry invalidates the advisory even when no new market tick arrives;
- no “last BUY” may remain visually active after its evidence expires;
- supervisor snapshot IDs / timestamps must permit replay and audit.

### AI disagreement

If GPT/Claude/other AI reviewers produce different interpretations:

- preserve each interpretation as advisory metadata;
- deterministic contract/risk state remains authoritative;
- unresolved AI disagreement is not converted into a trade;
- Chief supervisor reports CONFLICT / NEEDS_REVIEW when necessary.

### Voice

AI Strategy LIVE may speak:

- supervisor state changes;
- major conflict;
- Risk Gate block;
- data stale;
- candidate activation/invalidation.

Voice is informational only and cannot trigger execution.

### Journal handoff

AI Strategy LIVE emits sanitized high-level events such as:

- SUPERVISOR_STATE_CHANGED
- STRATEGY_CANDIDATE_ACTIVATED
- STRATEGY_INVALIDATED
- CONFLICT_DETECTED
- RISK_GATE_BLOCKED
- SHADOW_POSITION_OPENED
- SHADOW_POSITION_CLOSED
- DAILY_STRATEGY_SUMMARY

These can be consumed by the separate **Trading Journal System / AIトレード日記システム**.

Raw private MS2/account/order payloads must not cross that boundary.

---


## 4.7.3 Global Macro Supervisor / グローバルマクロ統括

The Strategy layer shall include a dedicated **Global Macro Supervisor / グローバルマクロ統括**.

Its output is a **Regime Modifier / 地合い補正要因**, not a direct BUY/SHORT trigger.

The purpose is to prevent Japanese-equity strategies from evaluating the same technical setup identically under materially different global macro conditions.

### Core macro inputs / 主要マクロ入力

At minimum, support point-in-time observations for:

| English | 日本語 | Role |
|---|---|---|
| US 2Y Yield | 米2年金利 | Near-term Fed policy expectations |
| US 10Y Yield | 米10年金利 | Growth/valuation pressure and long-rate regime |
| US 30Y Yield | 米30年金利 | Long-duration inflation/fiscal pressure |
| Japan 2Y JGB | 日本2年金利 | BOJ near-term policy expectations |
| Japan 10Y JGB | 日本10年金利 | Domestic long-rate regime |
| Japan 20Y / 30Y / 40Y JGB | 日本20年・30年・40年金利 | Super-long curve/fiscal pressure |
| US-Japan 2Y Spread | 日米2年金利差 | FX/policy differential context |
| US-Japan 10Y Spread | 日米10年金利差 | FX/cross-border capital-flow context |
| Real Yield | 実質金利 | Growth equities / Gold sensitivity |
| Breakeven Inflation | 期待インフレ率 | Inflation-expectation decomposition |
| WTI Crude Oil | WTI原油 | Inflation, energy, transport and cost pressure |
| Brent Crude Oil | ブレント原油 | Global energy / geopolitical shock context |
| Gold | ゴールド | Real-yield / USD / risk-aversion context |
| Copper | 銅 | Global/China growth-sensitive context |
| USD/JPY | ドル円 | Japanese exporters / imported inflation |
| VIX | VIX指数 | Global risk-off intensity |
| Nikkei Futures | 日経先物 | Immediate Japanese-equity market context |
| SOX / Nasdaq | SOX / NASDAQ | Semiconductor / growth risk context |

Do not infer unavailable values. Missing/stale inputs must remain explicitly missing/stale.

### Yield Curve Engine / イールドカーブ分析エンジン

The Global Macro Supervisor shall contain a dedicated **Yield Curve Engine / イールドカーブ分析エンジン**.

Minimum curve spreads:

#### United States / 米国
- 3m10y / 3か月-10年
- 2s10s / 2年-10年
- 5s30s / 5年-30年
- 10s30s / 10年-30年

#### Japan / 日本
- 2s10s / 2年-10年
- 5s10s / 5年-10年
- 10s20s / 10年-20年
- 10s30s / 10年-30年
- 10s40s / 10年-40年 where source coverage is reliable

Also track:

- current level;
- 1-session change;
- 5-session change;
- 20-session change;
- rolling z-score where sample size is adequate;
- inversion / normalization state;
- source freshness;
- observation timestamp;
- curve-regime classification.

### Curve regime classification / カーブ状態分類

At minimum classify:

- **Bull Steepener / ブル・スティープナー**
- **Bull Flattener / ブル・フラットナー**
- **Bear Steepener / ベア・スティープナー**
- **Bear Flattener / ベア・フラットナー**
- **INVERTED / 逆イールド**
- **NORMALIZING / 正常化中**
- **UNKNOWN / 判定不能**

Classification must use explicit deterministic rules and versioned thresholds. Do not let an LLM assign the curve state from prose alone.

### Macro interpretation / マクロ解釈

The system must not apply simplistic one-factor rules such as:

- "oil up => Nikkei short";
- "10Y yield up => semiconductor short";
- "inverted curve => sell today".

Instead, distinguish at least:

- growth-driven rate rise vs inflation-driven rate rise;
- supply-shock oil rise vs demand-driven oil rise;
- real-yield move vs inflation-expectation move;
- US-rate move vs Japan-rate move;
- widening vs narrowing US-Japan rate differentials;
- broad risk-off vs sector-specific weakness.

Where causal decomposition is not supported by evidence, state UNKNOWN rather than inventing a narrative.

### Strategy Router integration / Strategy Router連携

The Global Macro Supervisor output is consumed by:

~~~text
Global Macro Supervisor
        |
        +--> Market Regime Supervisor
        |
        +--> Sector Regime
        |
        +--> Strategy Router
                 |
                 +--> SCALP
                 +--> REALTIME / DAYTRADE
                 +--> OVERNIGHT
                 +--> SWING
                 +--> VALUE / LONG_CATALYST
                 +--> EVENT / TOB_MA where relevant
~~~

Use macro state to modify:

- strategy eligibility;
- LONG/SHORT priority;
- confidence band;
- position-size multiplier proposal;
- event lock / caution state;
- sector preference;
- overnight gap-risk treatment.

Do **not** use Global Macro or Yield Curve state as a standalone entry trigger.

Intraday technical triggers such as OR5/OR15/VWAP/EMA/Flow remain separately defined and versioned.

### Point-in-time and safety requirements

- every macro observation must carry observed_at, source, timezone, freshness and provenance;
- no revised/future macro value may leak into historical/backtest decisions;
- stale/missing macro data => UNKNOWN or strategy-specific fail-closed handling;
- no forward-fill across materially stale windows for decision use;
- historical research must use the value known at that historical timestamp;
- source disagreements must be preserved or reconciled explicitly;
- no macro component can bypass Risk Gate, Permission Gate, Conflict Resolver or Owner approval;
- real_submit_allowed remains false.

### Validation contract

Before any macro factor is allowed to affect live strategy ranking or risk sizing, test its incremental contribution separately.

At minimum report:

- N;
- EV;
- PF;
- max DD;
- MFE;
- MAE;
- slippage-adjusted result where relevant;
- confidence interval;
- regime stability;
- interaction with symbol class / sector / horizon.

If evidence is insufficient, status remains INSUFFICIENT_SAMPLE / UNKNOWN.

---

## 4.8 Strategy families

Initial Strategy Lab families:

### Intraday / scalping

- OR5
- OR15
- OR breakout
- VWAP pullback
- VWAP reclaim
- EMA trend/pullback
- volume expansion
- FVG
- Ichimoku
- large-tick / tape flow
- board imbalance
- time-of-day patterns

### Overnight

- close strength;
- end-of-day volume;
- catalyst;
- futures / US semiconductor context;
- gap statistics;
- event risk.

### Swing

- multi-day trend;
- relative strength;
- VCP / contraction-expansion;
- breakout;
- stage analysis;
- earnings/catalyst continuation.

### Long catalyst / value

- earnings;
- revisions;
- capital return;
- buybacks;
- valuation;
- balance sheet;
- structural catalyst.

### TOB / M&A

Separate event model.

### Speculative theme / event

Separate model for:

- theme ignition;
- sudden volume;
- TDnet/material confirmation;
- thin-liquidity risk;
- exhaustion / chase risk.

No single model should absorb all of these.

---

## 4.9 Backtest / research contract

Every research record should eventually support:

- strategy_id
- strategy_version
- horizon
- symbol_class
- liquidity_bucket
- regime
- side
- signal_time
- entry_trigger
- simulated_fill
- fees
- slippage
- MFE
- MAE
- exit_reason
- R
- pnl
- source

Minimum aggregate statistics:

- N
- win rate
- average R
- EV
- PF
- max drawdown
- MFE
- MAE
- slippage
- 95% CI

Required splits:

- in-sample
- out-of-sample
- walk-forward
- symbol class
- regime
- GU/GD/flat
- RVOL bucket
- time window

If N is insufficient, status is UNKNOWN / INSUFFICIENT_SAMPLE.

---

## 4.10 Scenario / Conflict Resolver

Multiple strategies may disagree.

The Conflict Resolver must:

- preserve all candidate evidence;
- resolve only under explicit deterministic rules;
- emit a merge/resolution hash where defined;
- never mutate old canonical semantics without migration;
- return WAIT/BLOCK when conflict is unresolved.

---

## 4.11 Risk Gate

`scripts/risk_gate.py` exists on main.

Purpose:

- compute allowed quantity;
- enforce risk policy;
- remain pure;
- not contact broker / Excel / RSS directly;
- fail closed on invalid inputs.

Future real-order readiness must add independent limits for:

- per-trade risk;
- daily loss;
- maximum positions;
- gross/net exposure;
- event locks;
- liquidity limits;
- kill-switch state.

---

## 4.12 Execution Contract

`scripts/execution_contract.py` exists on main.

Purpose:

- canonical intent/ticket schema;
- deterministic hash / fingerprint;
- state transitions;
- no broker side effect.

Canonical hashes are contracts. Do not casually change them.

If a new version is necessary:

- version the contract;
- preserve old replayability;
- add explicit migration semantics;
- never silently reinterpret historical evidence.

---

## 4.13 Permission / approval boundary

Owner approval must remain explicit.

Expected properties:

- no auto-approval;
- terminal approval/rejection decisions;
- actor/time audit;
- duplicate identity rejection;
- malformed input fail-closed.

There are older open draft PRs in this area. Claude must not merge them blindly because many were created against old main and are currently stale/conflicting.

---

## 4.14 Shadow execution / fill model

Shadow execution is the only execution mode currently authorized.

Requirements:

- deterministic shadow_order_id;
- duplicate prevention;
- strict known-order boundary;
- no repair of corrupt ledger;
- fill-model version lineage;
- no real-submit side effect.

Fill Model v0.1 is intentionally conservative/incomplete and includes assumptions that are not yet empirically calibrated.

Do not change Fill Model semantics merely because a better assumption seems plausible.

---

## 4.15 Shadow Position Lifecycle

`scripts/shadow_position.py` exists on main.

Core invariants:

- positive verified entry fill required;
- current quantity must conserve entry minus exit fills;
- over-exit must fail;
- CLOSED is terminal;
- rollback / impossible quantity changes fail;
- protective exits are modeled without broker side effects.

Open hardening PRs exist and need rebasing/review on latest main before merge.

---

## 4.16 Reconciliation

Two distinct concepts:

### Shadow reconciliation

Compare:

- intent;
- order;
- fill;
- position;
- lifecycle;
- replayed deterministic state.

### Future real reconciliation

Would compare:

- requested order;
- broker acknowledged order;
- broker open orders;
- fills;
- positions;
- cash / buying power where needed.

UNKNOWN must never trigger blind resubmission.

Real reconciliation is not an active broker path today.

---

## 4.17 Shadow Forward

`scripts/shadow_forward_acceptance.py` exists on main.

Purpose:

- replay private forward evidence through canonical pure functions;
- verify chronology;
- verify lineage;
- verify deterministic state;
- count eligible unique intents;
- report acceptance diagnostics.

Important current gate:

- public GitHub does not prove >= required genuine eligible forward intents;
- therefore Phase 6 operational acceptance remains HOLD / INSUFFICIENT_SAMPLE;
- synthetic or backfilled evidence must not be used to pass this gate.

Open work includes private local persistence and capture boundaries.

---

## 4.18 Fill Model Calibration

PR #166 is the active replacement calibration PR.

Recent GPT audit hardened:

- input-order determinism;
- conflicting duplicate handling;
- closed evidence schema;
- invalid-record fail-closed;
- explicit as-of requirement;
- model_version validation;
- per-base-stratum multi-session coverage;
- no automatic parameter update;
- no real submit.

Merge remains HOLD until latest-main reconciliation and final review.

Calibration cannot be completed statistically until genuine future MS2 evidence exists.

---

## 4.19 UI / voice

Target top tabs:

- SCALP 5
- EVENT 5
- REALTIME 5
- OVERNIGHT 5
- SWING 5
- VALUE 5
- KIOXIA
- 決算日程
- 注意
- 参考

UI rules:

- do not invent missing live values;
- stale/missing => CLOSED/BLOCK/WAIT_DATA;
- current-condition strength and historical EV are separate;
- critical state should be readable in seconds.

Voice:

- SBV2/local voice is allowed for notification;
- voice must not imply certainty unsupported by data;
- pronunciation normalization is allowed;
- duplicate/chattering alerts should be rate-limited;
- voice must never bypass Risk/Permission/Owner gates.

Several old draft voice/UI PRs exist against old bases. Consolidate/rebase; do not merge stale branches blindly.

---

## 5. Current verified progress

Legend:

- DONE = implemented and verified enough for its current scope
- PARTIAL = implementation exists, evidence or integration incomplete
- HOLD = intentionally not authorized / insufficient evidence
- TODO = not yet implemented to target architecture

| Area | State | Current note |
|---|---|---|
| GitHub source-of-truth discipline | DONE | main is canonical |
| Windows V6 runtime | PARTIAL | operational, but deployment/main drift must always be checked |
| MS2/Excel live acquisition | PARTIAL | substantial implementation; actual-market acceptance continues |
| External Heartbeat Watchdog | DONE | C-089 actual Windows PASS |
| TradingView 15s Replay overlap integrity | DONE for tested ranges | exact common-timestamp OHLCV matches verified |
| TradingView session-gap semantics | PARTIAL | Issue #167 / PR #168 and Issue #169 |
| Claude 15s handoff payload | TODO/PARTIAL | Issue #57 still requires real handoff payload |
| Strategy UI lanes | PARTIAL | UI exists; validated statistical router not complete |
| Strategy Router | TODO/PARTIAL | design exists; target implementation not complete |
| Strategy Lab unified statistics | PARTIAL | research exists, unified promotion framework incomplete |
| Execution Contract | DONE for pure contract scope | on main |
| Risk Gate | DONE for current pure scope | on main |
| Permission/Owner hardening | PARTIAL | stale draft PR backlog exists |
| Shadow Order hardening | PARTIAL | active open hardening PRs |
| Shadow Position Lifecycle | DONE/PARTIAL | core on main; adversarial hardening PRs open |
| Shadow Forward Acceptance | DONE for pure engine | operational evidence gate remains HOLD |
| Genuine Shadow Forward capture | PARTIAL | private/local persistence boundary incomplete |
| Fill Model v0.1 | DONE for current model | intentionally uncalibrated assumptions remain |
| Fill Model calibration | PARTIAL/HOLD | PR #166 draft, evidence still insufficient |
| Broker reconciliation | TODO for real path | do not activate early |
| Execution Orchestrator | TODO/HOLD | design only until prerequisites pass |
| Real submit | HOLD | explicitly disabled |

---

## 6. Open-PR hygiene

There are many old draft PRs created from older bases.

Examples currently open include:

- #155 private Shadow Forward path policy
- #157 known-order boundary
- #159 fill-model version lineage
- #161 quantity-conservation tests
- #163 fill-model assumption diagnostics
- #166 calibration evidence contract
- #168 TSE-session-aware Replay gap audit
- older Owner approval / Event / voice / UI PRs

Current rule:

1. never merge an old PR only because its tests once passed;
2. compare to current main;
3. classify as:
   - still needed;
   - already superseded;
   - conflict/rebase required;
   - close as obsolete;
4. re-run tests on current main;
5. review state transitions, not test count only;
6. merge only after GPT review where the change touches canonical contracts/safety.

---

## 7. Development role split

## 7.1 Owner / user

Owner responsibilities:

- final product intent;
- actual-machine access;
- MS2 login / credentials / 2FA;
- physical PC operation where required;
- final approval for destructive or operational changes;
- final approval for any future real-order activation;
- accepting/rejecting changes to financial risk policy.

The Owner should not need to manually perform routine coding, test writing, or documentation.

---

## 7.2 GPT

GPT responsibilities:

- architecture;
- strategy design;
- statistical validity;
- safety review;
- specification;
- issue design;
- code review;
- adversarial review;
- merge readiness decision;
- phase-gate decision;
- independent verification of important Claude claims against main/code/tests/Actions.

GPT must not treat “Claude says done” as proof.

---

## 7.3 Claude / Claude Code

Claude owns:

- implementation;
- refactoring;
- tests;
- local/repo diagnostics;
- GitHub updates;
- CI execution;
- implementation notes in STATUS.md;
- bridge response updates;
- long-running repository work;
- code-based backtests;
- non-broker automation.

Claude should operate issue-by-issue and must preserve canonical contracts unless the Issue explicitly authorizes versioned change.

---

## 7.4 GitHub Actions

Use for:

- unit/integration tests;
- static validation;
- deterministic regression tests;
- publication checks;
- generated public artifacts where safe;
- evidence that does not contain private runtime data.

Do not use GitHub Actions as a substitute for private actual-machine MS2 tests.

---

## 8. Can the system be built fully automatically?

Short answer:

### Software construction: mostly yes.

Claude + GPT + GitHub can automate a large majority of:

- coding;
- unit tests;
- integration tests;
- schema generation;
- validation;
- backtests;
- documentation;
- CI;
- PR creation;
- issue updates;
- deterministic replay;
- static safety review;
- synthetic/adversarial tests.

### Shadow operation: largely yes after local runner work is finished.

It is realistic to automate:

- market-data ingestion;
- feature calculation;
- strategy selection;
- scenario generation;
- Risk Gate;
- Shadow Execution;
- Position Lifecycle;
- evidence capture;
- acceptance statistics;
- alerts;
- daily reports.

### Complete unattended real trading: no, not under the current project policy.

Some steps must remain human-gated or actual-machine-gated:

- MS2 login / credentials / passkeys;
- first-time Excel/RSS setup;
- GUI-only TradingView Replay operations when no stable automation source exists;
- ambiguous data-source semantics;
- acceptance of materially changed risk policy;
- final authorization to enable any real submit path;
- emergency Kill Switch ownership;
- regulatory/account/broker operational decisions.

The correct target is therefore:

```text
highly autonomous development
+ highly autonomous Shadow trading
+ human-gated real execution
```

not “AI independently builds and trades real money with no owner gate.”

---

## 9. Autonomous development loop

Claude may work semi-autonomously using this loop:

1. pull latest main safely;
2. read:
   - CLAUDE.md
   - STATUS.md
   - docs/AI_SHARED_SHEET.md
   - docs/CLAUDE_BRIDGE_RESPONSES.md
   - this master specification
   - latest relevant Issue comments;
3. select only an approved/open task;
4. inspect main implementation before writing code;
5. write minimal change;
6. add adversarial tests;
7. run targeted tests;
8. run full CI;
9. inspect actual state transitions;
10. open/update Draft PR;
11. update STATUS.md;
12. update Claude bridge response with commit/test evidence;
13. stop before:
   - merge of safety-critical/canonical changes;
   - real-submit activation;
   - Scheduled Task activation where not pre-approved;
   - private-data upload;
14. wait for GPT/Owner gate when required.

Claude should continue through independent low-risk tasks without repeatedly asking the Owner for confirmation.

---

## 10. Immediate Claude execution queue

Priority is safety/infrastructure before new strategy complexity.

### P0 — repository / contract hygiene

1. Audit latest main versus all open draft PRs.
2. Produce a table:
   - PR;
   - still-needed?;
   - superseded-by;
   - behind/conflict;
   - canonical-risk;
   - recommended next action.
3. Do not merge.
4. Close nothing unless explicitly authorized.

### P1 — TradingView evidence semantics

1. Review Issue #169.
2. Design a pure classifier for:
   - EXPECTED_SESSION_BREAK;
   - UNRESOLVED_NO_BAR_INTERVAL;
   - VERIFIED_ACQUISITION_GAP.
3. Never synthesize missing OHLCV.
4. Use independent evidence when available.
5. Rebase/reconcile PR #168 onto latest main if safe.
6. Keep it Draft until GPT review.

### P2 — Claude 15-second handoff

Issue #57 remains open.

If Claude has actual acquisition capability:

- acquire TSE:285A / 15S / Asia/Tokyo;
- no substitute timeframe;
- emit documented handoff shape;
- run intake/route;
- return sanitized receipt metadata;
- do not publish raw private/local paths.

If acquisition is unavailable, report explicit BLOCKED reason instead of fabricating payload.

### P3 — Shadow Forward private persistence

Continue private forward evidence boundary work:

- append-only;
- private ignored root;
- capture timestamp stamped by runner;
- no historical backfill API;
- verified resume only;
- finalized record terminal;
- anchor/evidence mismatch => BLOCK.

Runner may be implemented inactive-by-default.

### P4 — Fill Model calibration

PR #166:

- rebase/reconcile to latest main;
- retain current deterministic/evidence-integrity fixes;
- no Fill Model behavior change;
- no automatic parameter update;
- no merge without GPT review.

### P5 — Strategy Router / Strategy Lab

After the safety backlog is stable:

- implement strategy_id/version;
- unified research result schema;
- asset profile;
- market regime;
- horizon router;
- EV/PF/DD/MFE/MAE/N outputs;
- no strategy promotion with insufficient N.

---

## 11. Estimated development period

Separate coding time from evidence time.

### 11.1 Coding / engineering time

Assuming Claude works continuously on approved tasks and GPT reviews gates:

#### Phase A — backlog normalization
Estimated: 1–3 working days

- open PR audit;
- rebase/supersession map;
- docs/status cleanup.

#### Phase B — TradingView/MS2 data semantics
Estimated: 2–5 working days coding
plus 1–5 market sessions for actual-machine evidence

- no-bar vs acquisition-gap semantics;
- session-aware stitcher;
- handoff/crosscheck;
- live tick diagnostics.

#### Phase C — Strategy Router + unified statistics
Estimated: 5–10 working days

- schemas;
- router;
- profile/regime;
- Strategy Lab result contract;
- UI wiring.

#### Phase D — private Shadow Forward capture/persistence
Estimated: 3–6 working days coding
plus forward-observation calendar time.

#### Phase E — calibration / reconciliation hardening
Estimated: 4–8 working days after enough evidence exists.

#### Phase F — future Execution Orchestrator dry-run
Estimated: 5–10 working days after Shadow acceptance and calibration pass.

Total remaining engineering effort to a strong Shadow-grade system:
approximately 3–6 weeks of focused development, depending on regression findings.

### 11.2 Statistical / operational validation time

This is the longer critical path.

Cannot be compressed by coding speed.

Expected:

- several market sessions for data-quality acceptance;
- multiple weeks to accumulate real forward samples;
- additional weeks for calibration strata if evidence must cover multiple order types/sides/regimes;
- walk-forward / out-of-sample periods for strategy promotion.

Practical high-confidence validation horizon:
approximately 6–12+ weeks, potentially longer for sparse event strategies.

Real-order readiness must be based on evidence, not calendar target.

---

## 12. Phase gates

### Gate 0 — source integrity
PASS only if:

- latest main known;
- no unreviewed local drift;
- CI green for relevant branch;
- private data boundary intact.

### Gate 1 — data integrity
PASS only if:

- provenance/timezone valid;
- stale/missing fail-closed;
- no synthetic repair;
- source overlap exact where required;
- ambiguous no-bar interval remains unresolved, not silently classified.

### Gate 2 — strategy research
PASS only if:

- strategy version fixed;
- sufficient N;
- fees/slippage included;
- OOS/walk-forward available;
- EV/PF/DD/MFE/MAE reviewed.

### Gate 3 — Shadow execution
PASS only if:

- deterministic;
- duplicate-safe;
- quantity conserving;
- terminal states enforced;
- no real submit.

### Gate 4 — Shadow Forward
PASS only if genuine point-in-time forward evidence reaches minimum contract requirements.

### Gate 5 — calibration
PASS only if:

- enough multi-session evidence;
- conflict-free evidence;
- parameter changes independently reviewed.

### Gate 6 — real-execution design review
Still no submit.

Requires:

- reconciliation;
- kill switch;
- UNKNOWN semantics;
- idempotency;
- owner approval model;
- maximum loss/position risk.

### Gate 7 — real-submit activation
Separate explicit Owner authorization only.

Not authorized by this specification.

---

## 13. Current critical path

The fastest safe path is:

```text
clean PR backlog
  -> close data semantics gaps
  -> finish private Shadow Forward persistence
  -> collect genuine forward evidence
  -> calibrate Fill Model
  -> complete Strategy Router statistics
  -> long Shadow run
  -> reconciliation / orchestrator dry-run
  -> Owner review
```

Do not prioritize new UI features over this path unless the UI change is required for safety/diagnostics.

---

## 14. What “done” means

The AI Cockpit is not “done” when:

- the page looks complete;
- Claude says implementation finished;
- unit-test count is large;
- backtest win rate looks high;
- one symbol performs well.

It is “ready for the next gate” only when:

- source code is on current main or reviewed PR;
- deterministic tests pass;
- actual state transitions were reviewed;
- actual-machine evidence exists where necessary;
- private-data boundary is intact;
- point-in-time semantics are valid;
- enough statistical evidence exists;
- failure behavior is fail-closed;
- the previous phase can be reproduced.

---

## 15. Claude reporting contract

Every Claude completion report should include:

- exact main SHA used;
- branch / PR;
- exact files changed;
- tests added;
- targeted test result;
- full CI result;
- state-transition evidence;
- whether canonical hashes changed;
- whether private data was touched;
- whether real-submit-related code changed;
- unresolved risks;
- next blocked dependency.

Forbidden report style:

- “done” without commit/test evidence;
- “should work” presented as actual-machine verification;
- inferred data represented as observed data;
- passing test count used as the only acceptance criterion.

---

## 16. Owner-facing operating model

The intended user experience is:

- Claude performs as much implementation/test work as possible;
- GPT independently reviews important changes;
- the user performs only:
  - actual-machine steps that require the PC;
  - logins/credentials;
  - final approval;
  - risk-policy decisions;
  - real-submit authorization if that future phase is ever reached.

The user should not be required to act as a manual build engineer.

---

## 17. Immediate instruction to Claude

On next Claude Code session:

1. pull/fetch latest main safely;
2. read this document plus CLAUDE.md / STATUS.md / AI_SHARED_SHEET.md / bridge responses;
3. acknowledge the current exact main SHA;
4. start with P0 and P1 above;
5. do every repository-only task that can be completed without actual-machine private data;
6. open Draft PRs, do not merge safety-critical changes;
7. do not activate Scheduled Tasks or real submit;
8. leave concise verified bridge responses;
9. continue until the next genuine Owner/GPT gate, rather than stopping after each trivial subtask.

---

## 18. Final target state

The mature system should be able to:

- automatically discover candidates;
- ingest live/historical evidence;
- detect data failure;
- select horizon-specific strategies;
- generate scenarios;
- calculate risk;
- run all trades in Shadow;
- reconcile Shadow state;
- measure EV and execution error;
- calibrate from future evidence;
- present only auditable decisions;
- notify the user;
- stop safely;
- require explicit human permission before any future real-money submit.

That is the definition of the AI Cockpit target architecture.
