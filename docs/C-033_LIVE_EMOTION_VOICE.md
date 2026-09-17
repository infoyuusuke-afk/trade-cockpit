# C-033 Live Emotion Voice Engine

## Goal

Add real-time presence to AI Cockpit voice without turning the voice into a blind buy/sell cheerleader.
The engine classifies the current Kioxia/MS2 state into four voice levels and changes both wording and SBV2 delivery.

## Levels

- `CALM`: low heat / wait
- `WATCH`: directional bias exists but acceleration is not confirmed
- `HOT`: multiple live conditions align strongly in one direction
- `DANGER`: stale data, whipsaw/chase guard, or explicit avoidance state

## Data used

Only fields already emitted by the MS2 collector are used. No missing market fact is inferred.

Primary inputs:

- `market_state`
- `breadth_pct`
- `kioxia.price`
- `kioxia.vwap`
- `kioxia.ema9`, `kioxia.ema20`
- `kioxia.or_high`, `kioxia.or_low`
- `kioxia.volume_burst`
- `kioxia.flow_bias`
- `kioxia.signal`
- `kioxia.strategy`
- `kioxia.common_decision`
- `kioxia.whipsaw`
- `kioxia.chase_guard`

## Heat model

The script builds LONG and SHORT heat scores (0-100) and compares the lead between them.

Examples of LONG evidence:

- strong market state / breadth
- price above VWAP
- EMA9 above EMA20
- OR15 upside break
- positive prints/flow bias
- live buy/long signal
- common decision confirms long

SHORT uses the symmetric conditions.

Volume acceleration raises urgency on both sides but does not decide direction by itself.

## Voice behavior

SBV2 delivery profile changes by level:

| Level | length | style_weight | split interval |
|---|---:|---:|---:|
| CALM | 1.20 | 0.35 | 0.60 |
| WATCH | 1.13 | 0.50 | 0.50 |
| HOT | 1.03 | 0.70 | 0.35 |
| DANGER | 1.10 | 0.80 | 0.45 |

The current `amitaro / Neutral` model may express most of the difference through wording and tempo. A later model with explicit emotion styles can map these same four levels to style names.

## Example phrases

### HOT LONG

```text
来た。キオクシア、ロング優勢。
出来高、加速。
歩み値も買い優勢。
VWAP上を維持。
いけいけムード。
ただし、高値追いは禁止。押し目だけ。
```

### HOT SHORT

```text
来た。キオクシア、ショート優勢。
出来高、加速。
歩み値も売り優勢。
VWAP下です。
下方向の熱量が高い。
ただし、追い売りは禁止。戻りを待ってください。
```

### DANGER

```text
危ない。キオクシア、往復ピンタ警戒です。
いったん追わない。
VWAPと板、歩み値が落ち着くまで待ってください。
```

## Anti-noise controls

- Poll every 3 seconds by default.
- State-change cooldown: 90 seconds.
- HOT repeat: only after 180 seconds and a meaningful score change.
- DANGER can repeat faster than normal states.
- Initial CALM is silent.
- Uses `Global\KioxiaVoiceMutex` to avoid overlapping with time/strategy voice.

## Safety behavior

- `HOT` wording can be energetic, but always includes an anti-chase discipline phrase.
- Fixed-time clock announcements do not claim live market conditions.
- Stale/insufficient MS2 data becomes DANGER instead of a directional call.
- No order placement is added or changed.

## Manual acceptance

1. Keep SBV2 API running at `127.0.0.1:5000`.
2. Start the normal MS2 flow from `START_MS2_100_LIVE.cmd`.
3. Confirm both hidden voice processes start:
   - `SPEAK_TODAY_STRATEGY.ps1`
   - `SPEAK_LIVE_EMOTION.ps1`
4. During live MS2 data, confirm the emotion voice only speaks on meaningful state change.
5. Confirm HOT LONG and HOT SHORT both include the anti-chase instruction.
6. Trigger/observe a whipsaw or chase-guard condition and confirm DANGER wording.
7. Stop SBV2 and confirm Windows SAPI fallback still works.
8. Confirm no collector/order/risk-gate behavior changes.

## Next candidate improvements

- UI switch: emotion voice ON/OFF.
- Separate volume sliders for clock / strategy / emotion voices.
- Explicit priority queue so DANGER can preempt lower-priority messages.
- Additional emotion-capable SBV2 model and style mapping.
- Record emitted voice events into a timestamped JSONL log for after-market review / Plaud alignment.
