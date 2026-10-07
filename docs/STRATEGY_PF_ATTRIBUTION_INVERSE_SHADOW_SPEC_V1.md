# STRATEGY PF ATTRIBUTION & INVERSE SHADOW SPEC v1.0
Updated: 2026-10-08 JST
Status: DRAFT FOR IMPLEMENTATION
Authority: 100億PROJECT canonical specification
Scope: Strategy attribution, PF ranking, inverse-signal validation, Shadow feedback

## 0. Purpose
The objective is to answer, at any time and without manual interpretation:
1. Which strategy judgment is making money?
2. Which strategy judgment is losing money?
3. Which losing signal has strong inverse value?
4. Which Supervisor / strategy / signal should be promoted, demoted, inverted, or blocked?
5. Is a poor PF caused by direction, entry timing, exit logic, market regime, stale data, or insufficient sample size?

This specification does not enable real orders.
`real_submit_allowed=false` remains mandatory.

## 1. Current-state facts
### 1.1 Strategy Supervisors defined
The current strategy layer defines 8 strategy-originating Supervisors:
- SCALP
- EVENT
- REALTIME_DAYTRADE
- OVERNIGHT
- SWING
- VALUE_LONG_CATALYST
- TOB_MA
- KIOXIA_DEDICATED

### 1.2 Currently connected in the repository Strategy LIVE mapping
Connected now:
- OVERNIGHT
- EVENT
- REALTIME_DAYTRADE
- VALUE_LONG_CATALYST

Not yet connected in that path:
- SCALP
- SWING
- TOB_MA
- KIOXIA_DEDICATED

Other Supervisors such as DATA_QUALITY, MARKET_REGIME, RISK_SAFETY, SHADOW_EXECUTION, RECONCILIATION, CALIBRATION, GLOBAL_MACRO, JOURNAL_CONTENT_EXPORT, and CHIEF_AI_STRATEGY are context/control roles and are not counted as independent entry-originating strategy agents for PF ranking.

### 1.3 Current Shadow limitation
The current `ai_shadow_supervisor.py` consumes Collector rows with:
- signal
- strategy
- price
- entry_price
- stop_price
- target1
- target2

It does not currently carry sufficient mandatory lineage tying every Shadow trade to one canonical Supervisor judgment.

Therefore a whole-Shadow PF can exist without proving which strategy judgment produced it.

## 2. Mandatory lineage contract
Every new Shadow candidate, entry, mark, exit, and rejected trade must preserve:

```text
decision_id
correlation_id
supervisor
strategy_id
strategy_version
signal_name
signal_family
side_original
side_executed
normal_or_inverse
decision_at
candidate_at
entry_at
exit_at
symbol
market_regime
source
source_timestamp
data_freshness_ms
entry_rule_id
exit_rule_id
stop_rule_id
target_rule_id
confidence
condition_score
real_submit_allowed
```

Constraints:
- decision_id is immutable.
- supervisor / strategy_id / signal_name may not be null for an accepted Shadow trade.
- normal_or_inverse must be NORMAL or INVERSE.
- real_submit_allowed must always be false.
- missing lineage => ATTRIBUTION_INVALID and exclude from PF ranking.
- stale/conflicting/unverified price source => fail closed and exclude from valid PF sample.

## 3. Signal-family taxonomy
Current Collector-facing entry signals must be normalized at minimum as:

LONG family:
- 初動買い候補
- 買いサイン
- 持ち越しロング確定

SHORT family:
- 初動ショート候補
- 空売りサイン
- 持ち越しショート確定

Each raw signal must map to:
```text
signal_name
signal_family
supervisor
strategy_id
```

No anonymous signal string may enter the ranked Shadow ledger.

## 4. NORMAL / INVERSE dual-run design
For every valid strategy decision, create two logically paired Shadow observations.

### 4.1 NORMAL
```text
LONG -> LONG
SHORT -> SHORT
```

### 4.2 INVERSE
```text
LONG -> SHORT
SHORT -> LONG
```

Both share:
- same decision_id
- same symbol
- same decision timestamp
- same observed market data
- same evaluation horizon
- same sampling clock

Derived IDs:
```text
shadow_variant_id = decision_id + ":NORMAL"
shadow_variant_id = decision_id + ":INVERSE"
```

## 5. Inverse comparison modes
### 5.1 INVERSE_DIRECTION_ONLY
Same entry and exit timestamps/prices; direction reversed before costs.
Purpose: measure directional information content only.
This is a research statistic, not a tradable PF.

### 5.2 INVERSE_TRADABLE
Run an actual inverse Shadow path with:
- side-correct entry logic
- side-correct stop geometry
- side-correct target geometry
- spread/slippage assumptions
- shortability/execution constraints where applicable

Only this can be considered for strategy promotion.

## 6. Timing analysis
Short opportunities can decay rapidly.
Required timing buckets where data allows:
```text
T0
T-30s
T-60s
T-120s
T-300s
```

No future information may be used.
If availability at the earlier timestamp cannot be proven:
`TIMING_VARIANT_INVALID_FUTURE_LEAK`

Output by timing bucket:
- N
- PF
- EV_R
- win rate
- avg MFE
- avg MAE
- median holding time
- max drawdown
- first-move capture rate

## 7. Core PF calculation
For closed, valid trades only:
```text
Gross Profit = sum(all positive realized Shadow P&L)
Gross Loss   = abs(sum(all negative realized Shadow P&L))
PF           = Gross Profit / Gross Loss
```

Rules:
- Open positions excluded.
- NOT_TRIGGERED excluded from trade PF.
- ATTRIBUTION_INVALID excluded.
- stale/fail-closed invalidated trades excluded.
- ambiguous order sequence excluded and counted separately.
- zero-loss samples display PF=INF.
- N always displayed next to PF.

## 8. Mandatory ranking dimensions
PF must be available by:
- Supervisor
- strategy_id
- raw signal
- side
- variant
- market regime
- session time bucket
- sector
- volatility bucket
- liquidity bucket
- HOT/NEXT source
- catalyst/no catalyst

## 9. Minimum daily report
Required columns:
```text
rank
supervisor
strategy_id
signal_name
variant
side
N
wins
losses
gross_profit
gross_loss
net_pnl
PF
EV_R
win_rate
avg_MFE
avg_MAE
max_DD
status
```

Status vocabulary:
- PROMOTE_CANDIDATE
- KEEP_TESTING
- INVERSE_CANDIDATE
- DEMOTE_CANDIDATE
- BLOCK_DATA_QUALITY
- INSUFFICIENT_N

## 10. Governance thresholds v1
These are provisional governance defaults, not proof of edge.

- N < 30 => INSUFFICIENT_N
- 30 <= N < 100 => watch sample only
- N >= 100 => formal review eligible if data quality valid

PF bands:
```text
PF >= 1.50  -> PROMOTE_CANDIDATE
1.10-1.49   -> KEEP_TESTING
0.90-1.09   -> NO_EDGE / KEEP_TESTING
0.50-0.89   -> DEMOTE_CANDIDATE
PF < 0.50   -> INVERSE_CANDIDATE
```

A value near PF 0.16 is not automatically discarded.
It is a high-priority INVERSE_CANDIDATE, subject to sample size and attribution validity.

## 11. Brain feedback contract
The PF engine never silently changes Brain behavior.
It publishes:
```text
supervisor
strategy_id
signal_name
normal_pf
inverse_direction_only_pf
inverse_tradable_pf
normal_ev_r
inverse_ev_r
N
confidence_band
recommended_action
evidence_window
updated_at
```

recommended_action:
- KEEP
- PROMOTE_REVIEW
- DEMOTE_REVIEW
- INVERT_REVIEW
- BLOCK
- INSUFFICIENT_DATA

Brain consumes this as evidence only.

## 12. Strategy count report
Always expose:
```text
strategy_supervisors_defined
strategy_supervisors_connected
strategy_supervisors_with_valid_pf
```

Current known repository state:
```text
strategy_supervisors_defined = 8
strategy_supervisors_connected = 4
strategy_supervisors_with_valid_pf = NOT_YET_CANONICALLY_AVAILABLE
```

Do not report "17 strategy agents".
The total Supervisor roster includes control/context roles.

## 13. Data-quality exclusions
Minimum reason codes:
- ATTRIBUTION_INVALID
- STALE_PRICE
- DATA_CONFLICT
- DUPLICATE_PROCESS
- WRONG_WORKBOOK
- MISSING_ENTRY
- MISSING_EXIT
- OPEN_POSITION
- NOT_TRIGGERED
- AMBIGUOUS_ORDER
- FUTURE_LEAK
- INVALID_SIDE_GEOMETRY
- FAIL_CLOSED_PERIOD

Daily report shows exclusion counts by reason.

## 14. Required artifacts
1. `strategy_shadow_ledger.jsonl`
2. `strategy_pf_daily_YYYYMMDD.json`
3. `strategy_pf_rolling.json`
4. `strategy_pf_ranking.json`
5. `strategy_inverse_comparison.json`
6. Cockpit UI card: top PF / worst PF / strongest inverse / N / latest timestamp / quality status

## 15. Acceptance criteria
A. Every accepted trade traces:
```text
Supervisor -> strategy_id -> signal_name -> decision_id -> Shadow entry -> Shadow exit
```

B. Same immutable ledger => identical PF output.

C. NORMAL and INVERSE never mixed.

D. Open positions never enter closed-trade PF.

E. Fail-closed trades never contaminate valid PF.

F. End-of-session answer available without manual log inspection:
- best PF strategy
- worst PF strategy
- strongest inverse candidate
- each N
- each net P&L

G. Report separately:
- defined strategy agents
- connected strategy agents
- PF-valid strategy agents

H. real_submit_allowed remains false.

## 16. Non-goals
This v1 does not:
- enable broker orders
- auto-promote to live trading
- let Brain self-modify production strategy
- assume PF alone is sufficient
- equate backtest PF with live Shadow PF
- infer missing attribution

## 17. Implementation order
Phase 1 — Attribution
Phase 2 — deterministic PF engine
Phase 3 — NORMAL/INVERSE paired comparison
Phase 4 — timing variants with anti-lookahead checks
Phase 5 — Brain feedback evidence
Phase 6 — UI/reporting

## 18. Definition of Done
DONE only when the Owner can ask:
- どの戦略判断のPFが一番良い？
- 一番悪いのは？
- 逆売買ならどう？
- 今何人の戦略エージェントが実際に判断してる？

and the system answers immediately from current valid Shadow evidence with:
- PF
- N
- net P&L
- NORMAL/INVERSE
- timestamp
- attribution
- exclusion reasons
- no manual log archaeology.
