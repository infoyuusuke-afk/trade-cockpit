# C-032 SBV2 Voice Bridge

## Purpose

Integrate the local Style-Bert-VITS2 API into the MS2/AI Cockpit voice path without touching order execution logic.

## Local prerequisite

- Style-Bert-VITS2: `C:\sbv2\Style-Bert-VITS2`
- API: `http://127.0.0.1:5000`
- Model: `amitaro`
- Speaker: `あみたろ`
- Style: `Neutral`
- Style weight: `0.4`
- Length: `1.2`
- Auto split: `true`
- Split interval: `0.7`

The user has manually verified `/status`, `/models/info`, and `/voice` with HTTP 200 and WAV output.

## Changes

### `ms2_live/SPEAK_TODAY_STRATEGY.ps1`

- Uses SBV2 `/voice` for speech.
- Falls back to Windows SAPI if SBV2 is down.
- Keeps the existing global voice mutex so multiple voice processes do not overlap.
- Adds speech-only text normalization:
  - `キオクシア` -> `きおくしあ`
  - `VWAP上` -> `ぶいわっぷ、うえ`
  - `VWAP下` -> `ぶいわっぷ、した`
  - `VWAP` -> `ぶいわっぷ`
  - `OR15` -> `おーあーる、じゅうご`
  - `OR5` -> `おーあーる、ご`
  - `EMA9` / `EMA20` / `EMA` -> hiragana-friendly pronunciation
  - `GU` / `GD` / `PF` / `%` -> pronunciation-friendly form
- Keeps display text separate from speech text.
- Adds one-shot market-clock announcements at 09:15, 09:30, 09:55, 10:00, 10:25, 11:00, 13:00, 14:00, 14:30, 15:00.
- Time-only announcements do not invent live facts such as VWAP/volume direction.

### `ms2_live/SPEAK_LIVE_EMOTION.ps1`

- Adds CALM / WATCH / HOT / DANGER live emotion states for Kioxia.
- Uses only fields already emitted by the MS2 collector.
- Builds LONG/SHORT heat scores from market state, breadth, VWAP, EMA, OR15, volume burst, flow bias, signal/strategy, common decision, and safety flags.
- Changes SBV2 tempo/style weight by emotion level.
- HOT wording can be energetic (`来た。`, `いけいけムード。`) but always retains anti-chase discipline.
- Uses cooldowns and the same global voice mutex to avoid chatter/overlap.
- Full design and acceptance criteria: `docs/C-033_LIVE_EMOTION_VOICE.md`.

### `ms2_live/START_MS2_100_LIVE.cmd`

- Checks `http://127.0.0.1:5000/status`.
- Starts local SBV2 API automatically if it is not running.
- Waits for API readiness.
- Launches both the strategy/time voice and live emotion voice processes.
- If SBV2 fails, MS2 continues and speech falls back to Windows SAPI.

### `ms2_live/START_SBV2_API.cmd`

Standalone SBV2 API launcher.

### `ms2_live/TEST_SBV2_VOICE.ps1`

Smoke test that generates and plays:

```text
9時55分です。
10時前の転換警戒に入ります。
きおくしあは、ぶいわっぷ、うえです。
出来高は増加しています。
新規ロングは慎重に。
```

## Safety scope

- No order placement changes.
- No Risk Gate / Permission Gate / Shadow Execution changes.
- No live market condition is fabricated by the fixed-time clock announcements.
- Existing SAPI fallback is retained.
- Emotional voice changes presentation and alerting only; it does not bypass execution safety.

## Manual acceptance test

1. Start SBV2 API or run `START_SBV2_API.cmd`.
2. Run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\ms2_live\TEST_SBV2_VOICE.ps1
   ```
3. Confirm the WAV is audible and pronunciation is natural.
4. Start normal MS2 flow with `START_MS2_100_LIVE.cmd`.
5. Confirm the Strategy Voice and Live Emotion processes start without changing collector behavior.
6. During a test window, confirm each clock event speaks at most once.
7. Confirm emotion voice only speaks on meaningful state change/cooldown and HOT phrases still include anti-chase language.
8. Stop SBV2 API and confirm a later speech event still speaks via Windows SAPI fallback.

## Next phase after acceptance

- Dynamic alert priority queue and DANGER preemption.
- UI voice ON/OFF and separate clock/strategy/emotion volume controls.
- Timestamped voice-event logging for after-market review and Plaud alignment.
- Additional emotion-capable SBV2 model/style mapping.
