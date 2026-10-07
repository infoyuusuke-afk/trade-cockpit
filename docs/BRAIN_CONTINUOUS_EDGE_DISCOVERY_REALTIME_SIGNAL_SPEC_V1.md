# BRAIN CONTINUOUS EDGE DISCOVERY & REALTIME SIGNAL SPEC v1.0
Updated: 2026-10-08 JST
Status: CANONICAL DRAFT — SPECIFICATION ONLY
Authority: 100億PROJECT
Scope: Brain definition, 365-day strategy discovery, validation, real-time strategy selection, signal publication, Shadow feedback

## 0. Executive definition

The **Brain** is the single central trading-intelligence agent for the AI Cockpit.

Its purpose is not to display system health and not to majority-vote fixed Supervisors.

Its purpose is:

> **365 days a year, continuously discover and ingest permitted trading-method information, validate every method under point-in-time-safe conditions, learn which method has the highest expected value for each market regime / symbol profile / time-of-day context, and during the TSE session publish the best current symbol + LONG / SHORT / NO-TRADE signal with full evidence and expiry.**

The number of internal strategies is not fixed.
The number of strategy Supervisors is not fixed.
The objective is to maximize verified expected value while preserving data integrity, reproducibility, safety, and Owner labor near zero.

`real_submit_allowed=false` remains mandatory.

---

## 1. Brain mission

Brain must continuously perform five functions:

1. **Discover**
   - find new candidate trading methods and signal ideas.
2. **Normalize**
   - convert each method into a canonical, testable strategy definition.
3. **Validate**
   - backtest, walk-forward test, replay test, and Shadow test without lookahead.
4. **Select**
   - rank strategies for the current context and choose the highest-quality actionable signal.
5. **Learn**
   - feed realized Shadow outcomes back into rankings, including inverse-signal evidence.

The permanent loop is:

```text
Strategy Discovery
    ->
Canonical Strategy Registry
    ->
Point-in-Time Backtest / Walk Forward / Replay
    ->
Shadow NORMAL + INVERSE
    ->
Contextual Edge Model
    ->
Realtime Selector
    ->
Symbol + LONG / SHORT / NO-TRADE
    ->
Shadow outcome
    ->
Recalibration / Promotion / Demotion / Inversion
    -> repeat forever
```

---

## 2. 365-day operating model

Brain operates continuously, but workload changes by market phase.

### 2.1 TSE session
Priority:
1. fresh market data
2. data-quality validation
3. candidate detection
4. strategy-context matching
5. realtime signal selection
6. signal publication
7. Shadow tracking
8. only then non-urgent research

Research jobs must not degrade live decision latency.

### 2.2 Pre-open / lunch / post-close
Perform:
- new strategy ingestion
- historical data updates
- parameter-free validation
- walk-forward updates
- strategy ranking refresh
- signal-quality attribution
- intraday timing analysis
- failure analysis
- replay of missed opportunities
- HOT/NEXT candidate research

### 2.3 Weekends / holidays / overnight
Perform:
- broad strategy discovery
- deeper backtests
- cross-validation
- robustness tests
- strategy deduplication
- regime segmentation
- inverse-signal research
- documentation / evidence compaction
- overseas-market contextual research

The Brain service should be designed as continuously running, restart-safe, idempotent, and able to resume from durable state.

---

## 3. Strategy discovery sources

Brain may discover candidate methods from permitted sources including:

- TradingView public scripts / public strategy descriptions where access and reuse are permitted
- Pine Script examples legally accessible to the system
- GitHub public repositories
- academic papers / SSRN / arXiv / journals
- broker / exchange educational material
- technical-analysis literature
- public quant research
- public blog / article strategy descriptions
- internal AI Cockpit historical strategies
- Owner-proposed ideas
- prior Shadow failure patterns
- discovered inverse relationships
- event / earnings / PR / theme logic
- order-flow / VWAP / OR / EMA / volume / volatility / regime combinations

### 3.1 Source compliance
Brain must not:
- bypass authentication, paywalls, rate limits, or access controls
- copy unavailable/private Pine source
- misrepresent proprietary code as owned
- use copyrighted source code beyond permitted use
- treat a textual strategy description as exact source code when code is unavailable

When exact code is unavailable, store only an independently specified method description with provenance.

### 3.2 Provenance
Every discovered method must have:
```text
discovery_id
source_type
source_url_or_reference
source_author_or_owner_when_known
discovered_at
license_or_usage_status
description
raw_claims
exact_code_available
research_notes
```

Unknown provenance => RESEARCH_ONLY.

---

## 4. Canonical Strategy Registry

No strategy may enter testing until normalized into a deterministic registry entry.

Required fields:

```text
strategy_id
strategy_version
strategy_family
origin
description
eligible_universe
eligible_session
required_timeframes
required_features
entry_rule
exit_rule
stop_rule
target_rule
time_stop_rule
side_capability
shortability_requirement
parameter_set
parameter_origin
expected_holding_period
data_requirements
freshness_requirements
known_failure_modes
provenance_refs
created_at
status
```

Allowed statuses:

- DISCOVERED
- NORMALIZED
- BACKTESTING
- WALK_FORWARD
- REPLAY
- SHADOW
- CHALLENGER
- CHAMPION
- INVERSE_CANDIDATE
- DEMOTED
- BLOCKED
- RETIRED
- RESEARCH_ONLY

Strategies must never be promoted because they are popular, famous, or recent.

---

## 5. No fixed number of strategies or strategy agents

The existing SCALP / EVENT / REALTIME_DAYTRADE / OVERNIGHT / SWING / VALUE_LONG_CATALYST / TOB_MA / KIOXIA_DEDICATED lanes are legacy/current strategy families, not the permanent Brain roster.

Brain may:
- keep them
- split them
- merge them
- demote them
- retire them
- add new strategy families

A strategy module earns continued use only through evidence.

The system must separately report:

```text
strategies_discovered_total
strategies_normalized_total
strategies_under_test
strategies_shadow_active
strategies_champion
strategies_challenger
strategies_inverse_candidate
strategies_demoted
strategies_retired
```

No fixed "8 strategy agents" target is allowed.

---

## 6. Context model — where an edge is valid

Brain must not rank a strategy only by global PF.

Every strategy must be evaluated conditionally by context.

Minimum context dimensions:

### 6.1 Time
- pre-open
- 09:00-09:05
- 09:05-09:15
- 09:15-09:30
- 09:30-10:00
- 10:00-10:30
- 10:30-11:30
- 12:30-13:00
- 13:00-14:00
- 14:00-14:30
- 14:30-15:00
- 15:00-close

Intervals may later be optimized from evidence rather than permanently fixed.

### 6.2 Market regime
At minimum:
- UP
- DOWN
- RANGE
- HIGH_VOL
- LOW_VOL
- RISK_ON
- RISK_OFF
- RATE_SHOCK
- SQ_EVENT
- POLICY_EVENT
- EARNINGS_HEAVY
- UNKNOWN

### 6.3 Symbol profile
At minimum:
- high price / high turnover
- large semiconductor
- large growth
- large value
- small growth
- speculative theme
- event / earnings
- TOB / M&A
- low liquidity
- high short-interest when valid
- HOT / momentum candidate

### 6.4 Market relationships
Where data is fresh:
- Nikkei vs TOPIX leadership
- sector leadership
- semiconductor leadership
- futures direction
- breadth
- FX
- rates
- volatility
- commodities
- PTS / overnight information

### 6.5 Setup state
Examples:
- OR5 / OR15 break
- VWAP reclaim / rejection
- EMA touch / rejection
- volume expansion
- gap continuation / gap fade
- high breakout failure
- low breakdown failure
- exhaustion
- reversal
- opening drive
- midday compression
- close auction / closing flow

A strategy's edge must be stored against the context where it was observed.

---

## 7. Validation hierarchy

No discovered strategy can directly become a realtime Brain recommendation.

Required validation path:

```text
DISCOVERED
-> NORMALIZED
-> historical backtest
-> out-of-sample / walk-forward
-> replay where possible
-> Shadow NORMAL
-> Shadow INVERSE
-> context-specific evaluation
-> CHALLENGER
-> eligible for CHAMPION review
```

Any unavailable stage must be explicitly marked unavailable; no fabricated PASS.

---

## 8. Anti-overfitting requirements

Brain must actively protect against strategy mining.

Required controls:
- train / validation / out-of-sample separation
- walk-forward windows
- point-in-time data only
- transaction-cost assumptions
- slippage assumptions
- short-side constraints
- minimum sample-size gates
- parameter-count penalty
- strategy-complexity penalty
- duplicate / near-duplicate strategy detection
- regime stability check
- time-of-day stability check
- symbol concentration check
- extreme-outlier dependence check
- multiple-hypothesis / data-mining awareness
- no promotion from one exceptional day
- no promotion from in-sample PF alone

Brain must preserve raw evidence sufficient to reproduce a result.

---

## 9. Core performance metrics

PF is important but not sufficient.

Required per strategy / context:

```text
N
wins
losses
gross_profit
gross_loss
net_pnl
PF
EV_R
EV_yen
win_rate
avg_win_R
avg_loss_R
median_R
avg_MFE
avg_MAE
max_drawdown_R
max_drawdown_yen
median_holding_time
signal_to_entry_latency
first_move_capture_rate
slippage_cost
turnover
stability_score
out_of_sample_pf
shadow_pf
inverse_shadow_pf
last_updated_at
```

Every ranking must display N beside PF / EV.

---

## 10. Primary optimization objective

Brain selects the strategy with the **highest validated conditional expected value**, not necessarily the highest raw PF.

Conceptual target:

```text
ContextualEdge(strategy, context)
  = validated expected return after costs
    adjusted for uncertainty
    adjusted for drawdown risk
    adjusted for sample sufficiency
    adjusted for execution latency
    adjusted for data quality
```

The first production implementation must use an explicit deterministic formula or ranking contract.
The formula must be versioned and auditable.

No LLM may silently change weights during runtime.

---

## 11. Champion / Challenger model

Brain continuously maintains:

### Champion
Best currently validated strategy for a defined context.

### Challenger
Promising strategies being tested against the Champion.

There may be different Champions by:
- time bucket
- regime
- symbol profile
- side
- setup

There is no requirement for one universal Champion.

A Challenger can replace a Champion only after acceptance thresholds are met.

Required promotion evidence includes:
- minimum N
- out-of-sample evidence
- Shadow evidence
- acceptable DD
- no data-quality violations
- no future leakage
- stable advantage after costs

Demotion may occur when:
- PF / EV degrades
- regime changes
- Shadow diverges from historical behavior
- latency makes the edge untradeable
- data source deteriorates
- inverse behavior becomes stronger

---

## 12. NORMAL / INVERSE learning

Every eligible signal must be evaluated as:

- NORMAL
- INVERSE_DIRECTION_ONLY
- INVERSE_TRADABLE

A persistently poor NORMAL signal may contain valuable directional information.

Brain must never automatically discard a strategy solely because PF is extremely low.

Instead:
- low PF + adequate N + stable opposite move => INVERSE_CANDIDATE
- test a tradable inverse version separately
- require independent evidence before promotion

The existing Strategy PF Attribution & Inverse Shadow specification remains the detailed contract for attribution and PF calculation.

---

## 13. Realtime selection engine

During the TSE session, Brain must repeatedly evaluate:

```text
current market context
x current symbol candidates
x eligible strategies
x fresh features
x historical conditional edge
x current Shadow evidence
x execution feasibility
```

Output candidates are ranked by validated expected value.

Brain must be able to output **NO-TRADE** when no candidate clears the threshold.

No obligation to trade exists.

---

## 14. Realtime signal contract

Every actionable Brain signal must include:

```text
brain_decision_id
generated_at
expires_at
symbol
name
side                  # LONG / SHORT / NO-TRADE
strategy_id
strategy_version
strategy_family
context_id
time_bucket
market_regime
entry
stop
target1
target2
time_stop
expected_value_R
expected_value_yen_when_valid
PF
N
out_of_sample_PF
shadow_PF
inverse_PF
confidence_band
signal_latency_ms
source_freshness_ms
rationale_codes
invalidation_codes
data_quality
real_submit_allowed
```

Rules:
- no signal without expiry
- stale signal immediately invalid
- NO-TRADE is a first-class output
- unknown EV must remain null, never fabricated as zero
- every signal must be replayable from its evidence snapshot
- real_submit_allowed=false

---

## 15. Signal speed / short-side requirements

For day trading, especially SHORT, correctness without speed may have no economic value.

Brain must measure:
- detection timestamp
- strategy decision timestamp
- publication timestamp
- theoretical first available entry
- actual Shadow entry
- first adverse/favorable move timestamp

Required latency metrics:
```text
discovery_latency_ms
feature_latency_ms
decision_latency_ms
publication_latency_ms
total_signal_latency_ms
```

For eligible setups, research variants:
- T0
- T-30s
- T-60s
- T-120s
- T-300s

Earlier variants are valid only when point-in-time evidence proves all required inputs existed then.

No lookahead.

---

## 16. Candidate universe integration

Brain must not be restricted to a permanently fixed list.

Inputs include:
- fixed core watchlist
- NEXT/HOT market-wide discovery
- TradingView scanners
- earnings/event candidates
- PTS movement
- theme propagation
- sector leaders
- unusual volume / turnover
- price acceleration
- new high / low behavior
- public catalyst feed

When a new symbol is promoted for realtime evaluation:
- preserve discovery reason
- preserve detection time
- attach fresh live data where available
- block strategy execution-quality claims when broker-grade live evidence is unavailable

---

## 17. Data source priority

The Brain must distinguish source roles.

### Live execution-grade / local decision facts where available
- MS2 RSS / verified local live data

### Research / discovery
- TradingView
- public market data
- public research sources
- event / news feeds

A research data source may discover a candidate without being sufficient to authorize a live-quality signal.

Source quality must be explicit.

---

## 18. Data-quality gate

Before an actionable signal:

```text
price_source_ok
timestamp_fresh
symbol_identity_ok
no_data_conflict
required_features_present
strategy_lineage_valid
context_lineage_valid
model_version_known
```

Any required failure =>
- WAIT_DATA
- BLOCK
- NO-TRADE

depending on reason.

Never fallback silently to stale values.

---

## 19. Brain and Shadow relationship

Brain is the decision engine.
Shadow is the measurement engine.

```text
Brain decision
-> attributed Shadow NORMAL / INVERSE
-> entry / fill / position / exit
-> PF / EV / MFE / MAE / DD / latency
-> Strategy Performance Store
-> Brain ranking update
```

Shadow must never originate an un-attributed trading idea.

A Shadow trade without `brain_decision_id` / `strategy_id` / `signal_name` is invalid for Brain learning.

---

## 20. Brain and existing Supervisors

Existing Supervisors become internal specialist inputs, not equal co-owners of the final decision.

Examples:
- Market Regime Supervisor -> context
- Global Macro Supervisor -> context modifier
- Data Quality Supervisor -> gate
- SCALP / EVENT / DAYTRADE / OVERNIGHT / SWING etc. -> strategy families or specialist modules
- Risk & Safety -> block / constraint
- Shadow Execution -> evaluation only

The **Brain Realtime Selector** owns the final advisory output:
- LONG
- SHORT
- NO-TRADE

while preserving the contributing strategy evidence.

No majority vote.

---

## 21. Brain state / persistence

Brain must persist:

- Strategy Registry
- Strategy versions
- test results
- walk-forward results
- Shadow results
- inverse results
- contextual ranking tables
- Champion / Challenger state
- discovered source provenance
- rejection / retirement reasons
- current context state
- current active signals
- decision ledger
- model/ranking version

Restart must not erase evidence or duplicate decisions.

---

## 22. Required durable artifacts

Target logical artifacts:

1. `brain_strategy_registry.jsonl`
2. `brain_strategy_evidence.jsonl`
3. `brain_context_edge_table.json`
4. `brain_champion_challenger.json`
5. `brain_realtime_decisions.jsonl`
6. `brain_active_signals.json`
7. `brain_discovery_log.jsonl`
8. `brain_rejected_strategies.jsonl`
9. `strategy_shadow_ledger.jsonl`
10. `strategy_pf_ranking.json`

Actual storage may use SQLite where appropriate, but schemas and export contracts remain canonical and inspectable.

---

## 23. Research scheduler

The research scheduler must distinguish:
- LIVE_CRITICAL
- SESSION_SUPPORT
- POST_CLOSE
- DEEP_RESEARCH

Live-critical work may preempt deep research.

Research jobs must be:
- idempotent
- retry-bounded
- provenance-preserving
- rate-limit-aware
- resumable
- failure-visible

No infinite hidden retry loops.

---

## 24. Continuous discovery quality control

A discovered method must not consume unlimited resources.

Required early rejection filters:
- source not permitted
- no deterministic specification possible
- data requirements unavailable
- clear lookahead dependence
- impossible execution assumptions
- duplicate of existing strategy
- insufficient liquidity scope
- invalid short assumption
- unrealistic fills
- no reproducible entry/exit definition

Brain should spend deeper compute only on surviving candidates.

---

## 25. Reporting

### 25.1 Live report
At any time during the session, Brain should be able to answer:
- strongest current candidate
- symbol
- side
- strategy
- EV
- PF / N
- confidence
- entry / stop / targets
- expiry
- why now
- data freshness
- Shadow state

### 25.2 Daily report
After close:
- signals issued
- signals expired unused
- NORMAL PF
- INVERSE PF
- best strategy by context
- worst strategy
- strongest inverse candidate
- missed first-move opportunities
- latency losses
- strategy promotions / demotions
- newly discovered strategies
- strategies rejected
- data-quality incidents

### 25.3 Weekly / rolling report
- 5-day / 20-day / all-valid-history
- Champion changes
- regime-specific performance
- time-of-day performance
- symbol-profile performance
- strategy decay
- strategy duplication
- portfolio of signals

---

## 26. Owner experience

Owner target is near-zero operation.

Owner should not:
- manually add discovered strategies
- manually calculate PF
- manually compare time buckets
- manually decide which strategy to Shadow
- manually move data between Brain and Shadow
- repeatedly inspect logs

Owner should receive concise actionable outputs and exception alerts only.

---

## 27. Safety boundaries

This specification does not authorize live broker execution.

Mandatory:
- `real_submit_allowed=false`
- no broker order submission
- no removal of fail-closed gates
- no silent data fallback
- no future-data leakage
- no autonomous modification of safety policy
- no autonomous expansion into inaccessible/private sources
- no publication of private MS2/account data

Future real trading requires a separate explicit Owner authorization and separate acceptance program.

---

## 28. Acceptance criteria

### A. Continuous research
Brain can ingest new permitted strategy candidates automatically and preserve provenance.

### B. Deterministic normalization
Every tested strategy has a versioned deterministic specification.

### C. Contextual evaluation
The same strategy can have different rankings by time / regime / symbol profile.

### D. No fixed roster
System supports strategy addition, retirement, merge, split, and inversion without assuming 8 permanent strategy agents.

### E. Realtime selection
During the TSE session, Brain can output the current best eligible symbol + LONG / SHORT / NO-TRADE from fresh data.

### F. Signal evidence
Every signal exposes strategy, EV, PF, N, context, timestamp, expiry, freshness, and invalidation.

### G. Shadow attribution
Every valid Shadow result links back to one Brain decision and one strategy version.

### H. Inverse learning
Extremely poor but stable signals can be tested as inverse candidates rather than discarded.

### I. Latency
Signal timing and missed first-move opportunity are measurable.

### J. Anti-lookahead
Walk-forward, replay, timing variants, and realtime decisions are point-in-time safe.

### K. Restart safety
A Brain restart resumes durable state without losing rankings or duplicating decisions.

### L. Owner zero-operation
Normal research / ranking / Shadow feedback requires no Owner manual work.

### M. Safety
No path created by this spec can submit a real broker order.

---

## 29. Definition of Done

Brain v1 is complete only when, without manual analysis, the system can continuously answer:

1. **今この瞬間、最も期待値の高い銘柄と売買方向は何か？**
2. **なぜその戦略が今の時間帯・地合い・銘柄で一番なのか？**
3. **その戦略のPF / EV / N / DD / Shadow実績は？**
4. **今のサインは何秒遅れているか？**
5. **通常方向と逆方向のどちらが強いか？**
6. **現在のChampion戦略は何か？**
7. **新しく発見されたChallengerは何か？**
8. **どの戦略が劣化し、どの戦略が昇格したか？**
9. **NO-TRADEが最適なら、なぜ見送るのか？**

and all answers are traceable to durable point-in-time evidence.

---

## 30. Relationship to existing specifications

This specification supersedes any interpretation that the Brain is only:
- a health dashboard
- a fixed 8-Supervisor committee
- a majority-vote aggregator
- a static Strategy LIVE display

Existing specifications remain valid for their narrower domains:
- V10 lifecycle / safety
- Strategy PF Attribution & Inverse Shadow
- Data Quality
- NEXT/HOT
- Shadow execution / evidence

Where wording conflicts, this document defines the Brain's higher-level trading-intelligence role while safety contracts remain non-negotiable.
