# Kioxia Breaking Radar

Public, read-only fast monitoring for Kioxia Holdings (285A).

## Goal

Reduce the delay between a public Kioxia/ADR development and AI Cockpit awareness without turning rumors into trading commands.

## Cadence

GitHub Actions runs every 5 minutes, 24/7, at an offset from the top of the hour. GitHub scheduled runs are best-effort and may be delayed by platform load, so this is not a guaranteed real-time feed.

The workflow uses a dedicated concurrency group so it is not queued behind bulk market-data writers. It writes only `kioxia_breaking_radar.json` and `data/kioxia_breaking_log.jsonl`, rebases before push, and retries non-force pushes.

## Sources

1. Kioxia Holdings official IR page — direct polling.
2. Kioxia Holdings official news page — direct polling.
3. SEC EDGAR — Kioxia CIK `1773708` submissions JSON first, company Atom fallback second. Source health stays fail-closed if GitHub-hosted runners are rejected.
4. Targeted Google News RSS queries — media discovery plus an explicit SEC-form/CIK fallback query. SEC-like hits from this fallback remain `SEC_DISCOVERY_UNVERIFIED` until primary-source confirmation.

The free JPX/TDnet public disclosure viewer is **not scraped** because JPX asks users not to automate scraping of that viewer. A licensed TDnet API/feed can be added later as an authenticated adapter.

## Evidence classes

- `OFFICIAL_TERMS`: company-confirmed ADR/listing terms.
- `CONFIRMED_PREPARATION`: company-confirmed preparation without final terms.
- `SEC_FILING`: direct EDGAR filing evidence.
- `SEC_DISCOVERY_UNVERIFIED`: filing-like discovery from the independent news-search fallback while direct EDGAR access is unavailable; this is an alert to verify, not primary-source confirmation.
- `REPORTED_TERMS`: major-media report, not company-confirmed.
- `UNCONFIRMED_RUMOR`: other ADR/listing media mention.
- `OFFICIAL_NEWS`: other company news.
- `MEDIA_MENTION`: other media discovery.

Every event stores source, URL, publication timestamp/date, first detection time, priority and evidence stage. Headlines never become BUY/SHORT signals.

## Alerting

New events with priority >= 85 and recent publication time are posted to Issue #179 with an @mention. Initial bootstrap is silent so historical backfill does not generate a false breaking alert.

## Safety

Public data only. No MS2/account/order/fill/holding/private data. No RssOrder, broker submit or real-submit. `trading_enabled=false` and `real_submit_allowed=false` are explicit in the output.
