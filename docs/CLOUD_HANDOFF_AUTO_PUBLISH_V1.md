# CLOUD HANDOFF — Auto Publish System V1

Date: 2026-09-25 JST
Branch: design/auto-publisher-v1
Owner intent: Build a post-market automated publishing system independent from AI Cockpit.

## Direction

1. Treat this as a separate product. No coupling to Excel/MS2/Collector/Watcher/Gateway/VoiceBridge.
2. First milestone is R1 DRY-RUN, not public posting.
3. The system automatically converts post-market evidence into:
   - English short-form video draft
   - English/Japanese post text
   - schedule candidates for Europe/North America
   - evidence manifest
4. Human approval remains mandatory in R1.
5. Production auto-publish is only unlocked after platform authorization, test history, and kill-switch validation.
6. Platform timing must start from baseline windows, then optimize from the account's own metrics.
7. Do not fabricate returns, trades, fills, timestamps, or market facts.
8. Paper/shadow results must be explicitly labeled as such.
9. All social posting adapters must be isolated behind interfaces and disabled by default.
10. Never modify trading/order code.

## Initial development target

Implement R1 DRY-RUN from:
- docs/AUTO_PUBLISH_SYSTEM_SPEC.md
- docs/CLOUD_BUILD_PROMPT_AUTO_PUBLISH_V1.md

Expected engineering sequence:
Day 1-2: schemas, SQLite queue, ingest/evidence hashing, state machine.
Day 3-4: story selection, factual validation, localization, compliance.
Day 5-6: FFmpeg vertical renderer, captions, deterministic artifacts.
Day 7: approval CLI, scheduler, dry-run payloads, CI acceptance.

Target first usable dry-run: 5-7 engineering days.
Target YouTube private pilot: roughly 2 weeks.
Target robust multi-platform V1: 4-6 weeks, platform review time excluded.

## Environment recommendation

Primary:
- Python 3.12
- SQLite
- FFmpeg
- Playwright (visual/card rendering where useful)
- APScheduler initially
- GitHub Actions CI
- Windows Task Scheduler for local post-market trigger

AI coding:
- Claude Code/Cloud: primary multi-file builder
- ChatGPT: architecture, acceptance criteria, review, integration decisions
- GitHub Copilot Pro for one-month burst if Cloud quota becomes a bottleneck
- Codex as independent reviewer/test agent where useful

## First report back

Report:
- branch/head SHA
- files created
- architecture summary
- test count/result
- one deterministic DRY-RUN artifact path
- blockers
- exact next task
- do not merge main

## Non-negotiable safety boundary

The publisher must never:
- call RssOrder
- submit broker orders
- modify trading positions
- use AI Cockpit runtime ports
- stop or restart AI Cockpit processes
- publish unsupported performance claims
