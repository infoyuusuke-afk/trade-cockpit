# AUTO PUBLISH SYSTEM V1 — Specification

Status: DESIGN / independent from AI Cockpit runtime
Date: 2026-09-25
Owner: YUSUKE IMAI
Target: Post-market automated content production, scheduling, publishing, and learning for overseas audiences.

## 1. Product goal

Build an autonomous content-distribution system that is operationally independent from the trading runtime.

The system must turn post-market evidence into publishable, factual, bilingual social content after the Tokyo market closes, schedule it for target audiences in Europe and North America, publish through supported official APIs, collect performance metrics, and continuously improve posting windows and formats.

The system is NOT allowed to:
- submit, modify, or cancel brokerage orders;
- connect to RssOrder or any real-order path;
- alter AI Cockpit runtime, Excel/MS2, Collector, Watcher, Gateway, VoiceBridge, or ports 28580/28581/28582/28583;
- fabricate prices, fills, P/L, timestamps, opportunity signals, or trading outcomes;
- publish a performance claim that cannot be traced to an evidence artifact.

## 2. Independence boundary

Recommended long-term repository: `trade-content-publisher`.

During bootstrap it may live on branch `design/auto-publisher-v1` in `trade-cockpit`, but production deployment must be separable.

One-way data flow only:

AI Cockpit / trading records
        |
        | post-market export (read-only copy)
        v
content_drop/YYYY-MM-DD/
        |
        v
AUTO PUBLISH SYSTEM

No inbound control path from publisher to AI Cockpit.

## 3. Source inputs

V1 supported inputs:
- daily market/trade summary JSON;
- `condition_log.csv` / Opportunity Radar event export;
- `paper_trade_history.json`;
- weekly review JSON;
- selected screenshots exported after session;
- optional Plaud transcript / trader monologue text;
- manually dropped images or short clips;
- optional public market/news citations gathered by a research stage.

Every generated story stores `source_refs[]` containing exact file path, hash, timestamp, and extracted fact.

## 4. Pipeline state machine

`INGEST -> VALIDATE -> STORY_SELECT -> FACT_CHECK -> SCRIPT -> LOCALIZE -> ASSET_RENDER -> APPROVAL -> SCHEDULE -> PUBLISH -> VERIFY -> METRICS -> LEARN`

Failure at any stage is fail-closed.

Publishing must never occur when:
- source evidence is missing;
- file timestamp/date mismatches the target session;
- content contains an unsupported profit claim;
- OAuth token is invalid;
- platform adapter reports uncertainty;
- compliance rules reject the draft.

## 5. Content products

Priority order:

### A. English short-form video (primary growth format)
- 20–45 seconds
- 9:16, 1080x1920
- English narration + burned-in English captions
- optional short Japanese subtitle line
- one idea per clip
- no watermark added for TikTok export
- source/evidence card retained internally, not necessarily rendered publicly

Example story types:
- “What moved Japan semiconductor stocks today?”
- “The volume spike I almost missed in Tokyo Electron”
- “One signal that changed after OR15”
- “AI trading cockpit: what it detected vs what I saw”
- “One mistake from today’s scalp session”

### B. X / text thread
- 1 hook post + 2–5 evidence posts
- chart/image optional
- concise English
- link back to longer video only when useful

### C. YouTube Shorts
- same master vertical video, platform-safe metadata
- unique title/description/hashtags

### D. TikTok / Instagram Reels
- adapter support after app authorization/audit requirements are met
- if direct-public posting is not approved, produce an upload-ready draft and stop before public publish

## 6. Global scheduling strategy

There is no single global “best hour”. The scheduler targets local audience windows.

Initial launch target: English-speaking trading/AI audience.

### Post-market production window (JST)
- 15:35–16:00 ingest and evidence lock
- 16:00–16:40 story selection / script
- 16:40–17:20 render / captions / QA
- by 17:30 queue must be ready

### Initial publish waves

Europe wave:
- 22:00–00:00 JST
- approximately mid-afternoon UK / Europe depending DST
- best for TikTok/Instagram test content and X recap

North America wave:
- 05:00–07:00 JST next day for TikTok tests (US afternoon)
- 08:00–10:00 JST next day for YouTube Shorts / US evening
- X may use 20:30–22:00 JST for US premarket/day-start context when the story is Japan-market-specific

The system must not hard-code these forever.

After 14 days or >=30 published posts per platform, `TimingOptimizer` must rank candidate slots using the account’s own:
- 1h impressions/views
- 24h views
- average watch duration / retention
- likes/shares/comments
- follower conversion
- geography/language where available

Generic timing priors become only a baseline after account-specific data exists.

## 7. Platform adapters

Interface:

```python
class PublisherAdapter:
    validate_credentials()
    validate_asset(asset)
    create_draft(post)
    schedule(post, publish_at)
    publish(post)
    verify_publish(publish_id)
    fetch_metrics(publish_id)
```

Adapters:
- `youtube.py`
- `tiktok.py`
- `instagram.py`
- `x.py`
- `dry_run.py`

V1 rule: `dry_run` is mandatory and must pass before any real adapter can be enabled.

YouTube:
- OAuth2 + YouTube Data API
- store upload result ID and verify final visibility
- unverified API projects may be restricted; treat visibility restrictions as a blocker, not success

TikTok:
- Content Posting API
- `video.publish` or upload scope as appropriate
- unaudited direct-post clients can be restricted to private visibility
- public automation remains disabled until app audit/authorization succeeds

Instagram:
- use official Meta publishing APIs only
- account/app eligibility checked before enabling adapter

X:
- isolate behind adapter because API availability/pricing can change
- scheduler must operate even if X adapter is disabled

## 8. Story selection engine

Candidate story score:
- novelty
- magnitude of market move
- volume anomaly
- Opportunity Radar event quality
- contrast between AI detection and human observation
- learning value
- visual clarity
- evidence completeness
- repeat-topic penalty

Do not optimize only for sensationalism.

A dramatic price move with weak evidence must rank below a smaller move with complete evidence.

## 9. Localization

Canonical story object is language-neutral facts + source refs.

Then generate:
- `en-US` primary
- `ja-JP` secondary
- future: `en-GB`, Korean, Chinese only after demand is demonstrated

Financial phrasing rules:
- describe observations, not guarantees;
- distinguish paper/shadow results from real account performance;
- avoid “guaranteed”, “easy profit”, “must buy/sell” wording;
- mark hypothetical/paper results explicitly.

## 10. Asset renderer

Recommended V1:
- Python 3.12
- FFmpeg for video assembly/transcode
- Pillow for static overlays
- optional HTML/CSS template rendered by Playwright for premium cards
- local TTS adapter initially; provider abstraction for later voice changes
- subtitles generated from the final approved script, not a separate model draft

Output:
```
artifacts/YYYY-MM-DD/<story_id>/
  master_1080x1920.mp4
  cover.jpg
  captions.srt
  post_en.json
  post_ja.json
  evidence.json
  render_manifest.json
```

## 11. Orchestration

Python service layout:

```
auto_publish/
  app/
    ingest/
    evidence/
    story/
    localization/
    render/
    compliance/
    scheduler/
    publishers/
    metrics/
    optimizer/
  config/
  templates/
  tests/
  migrations/
  cli.py
```

Runtime:
- SQLite in V1
- APScheduler for local MVP
- Windows Task Scheduler starts post-market job
- cloud-ready scheduler abstraction for later migration
- no dependence on AI Cockpit process lifecycle

## 12. Secrets and credentials

Never commit:
- OAuth refresh tokens
- client secrets
- API keys
- platform cookies
- account passwords

Use:
- Windows Credential Manager or encrypted local secret store for local MVP
- GitHub Actions secrets only for CI-safe test credentials
- separate OAuth app per environment if platform permits

## 13. Human control

Phase 1:
- automatic generation
- human approval required before publish

Phase 2:
- auto-publish only for templates with >=20 successful reviewed posts and no compliance failures

Always provide:
- PAUSE ALL
- DISABLE PLATFORM
- CANCEL SCHEDULED POST
- REVOKE TOKEN
- show queue
- show evidence
- show exact final caption/script

No hidden publishing.

## 14. Metrics and learning

Store per post:
- platform
- audience region target
- publish time UTC/JST/local target time
- hook/template/version
- duration
- language
- 1h/24h/7d views
- retention/watch time where available
- likes/comments/shares
- follows/subscribers
- clickthrough where available

Timing optimizer starts only after enough observations; otherwise retain baseline schedule.

## 15. Development plan

### Phase 0 — 1–2 days
- spec/contracts
- repository isolation
- schema
- dry-run publisher
- evidence hashing
- no external publishing

### Phase 1 — 4–5 days
- ingest
- story queue
- English/Japanese draft generation
- FFmpeg vertical template
- approval UI/CLI
- local scheduler

### Phase 2 — 4–7 days
- YouTube adapter + OAuth
- publish verification
- metrics ingestion
- retry/idempotency

### Phase 3 — 5–10 days
- TikTok adapter
- Instagram adapter
- X adapter if commercially reasonable
- account/app review work
- queue fallback when a platform cannot direct-publish

### Phase 4 — 5–7 days
- TimingOptimizer
- A/B hook/template tracking
- overnight scheduling
- monitoring/dashboard
- recovery drills

Engineering MVP: ~2 weeks if one coding agent works steadily.
Robust multi-platform V1: ~4–6 weeks, with platform app audits potentially extending calendar time.

## 16. Development environment / AI coding strategy

Primary recommendation:
- Claude Code/Cloud for large multi-file implementation because it already has project context and has been productive on this repository.
- Keep tasks branch-scoped and contract-test driven.
- Never let the agent merge to main automatically.

Low-cost overflow:
- GitHub Copilot Free for small edits/review.
- One-month GitHub Copilot Pro is a cost-effective burst option when agent/cloud capacity is needed.
- Google Antigravity CLI may be used as a secondary independent reviewer/builder using individual Google OAuth, but do not make production delivery dependent on its quota.

Optional one-month paid burst:
- Claude Pro for one month if Claude Code capacity is the bottleneck.
- Cancel after foundation if the free/low-cost tools are sufficient for maintenance.

## 17. CI acceptance

Required:
- unit tests for every pipeline state
- golden tests for story JSON
- FFmpeg render smoke test
- OAuth adapters mocked by default
- no real publish in CI
- idempotency test: same story cannot publish twice
- timezone/DST tests
- secret scan
- evidence trace test
- compliance rejection test
- platform-disable test

## 18. Release gates

R0 DESIGN:
- docs only

R1 DRY-RUN:
- produces complete artifact package and schedule
- does not contact publish APIs

R2 YOUTUBE PILOT:
- one private/unlisted test account
- verify upload + metrics

R3 MULTI-PLATFORM APPROVAL:
- TikTok/Instagram authorization completed
- manual approval remains mandatory

R4 AUTO:
- only after 20+ reviewed successful posts/template
- platform kill switch tested

## 19. First Cloud implementation task

Build R1 DRY-RUN only.
Do NOT implement public auto-posting in the first PR.
Do NOT touch AI Cockpit runtime.
Do NOT change real trading/order code.
