# P0 per-symbol freshness research and durable journal — Draft only
PROJECT_ITEM_ID: P0-V10-PER-SYMBOL-FRESHNESS-PRIVATE-JOURNAL-20261020

Based on coordinator Issue #282 message_id COORD-CLAUDE-AUDIT-DECISION-20261020-01.
Separates Collector heartbeat from quote available_at; an unchanged quote alone
is not proof of failed collection. Reports each row with explicit denominator.
No partial-board aggregate becomes trading-valid; derived values are WITHHELD.

Implementation scripts/v10_per_symbol_private_journal.py is an **unconnected**
synthetic research helper. Journal on POSIX is append/fsync, hash-chain verified
by fresh reads, and rejects same-session same-time replay. No automatic network,
MS2 access, Excel, Windows activation, UI, existing watchlist, source pin, orders,
merge, workflow or task changes. Windows-native safe append is deliberately
NOT_ACCEPTED: it fails closed. A caller must arrange an exclusive writer lock;
this draft is not concurrent-writer safe, source-authenticated, or deployable.

Acceptance is limited to synthetic negative tests. Future work is a Windows
private writer with atomic durable/restart evidence and independent readback,
then stable integration on a separately approved V10 candidate branch. No owner
runtime action is authorized. No real market data is published.

Never broaden 120-second rule or conflate quote freshness with heartbeat.
real_submit_allowed=false. Net realized economics UNKNOWN.

## Windows-compatible SQLite candidate added (not production acceptance)
`sqlite_candidate_append` and `sqlite_candidate_read` reapply the project's
existing `shadow_forward_windows_sqlite_candidate.py` SQLite pattern:
`BEGIN IMMEDIATE`, `PRAGMA synchronous=FULL`, rollback-journal mode,
immutable rows keyed by session+evaluated_at and independent connection readback.
Do **not** use the preexisting Shadow Forward DB or mutate its immutable ledger.
This is a separate experimental research-data file with an explicit private path
outside the repository. A replay/restart reads its retained hash chain.

Limits: Windows power-loss durability, filesystem path races (symlink/reparse
points), SQLite connection conflict timing on OWNER storage, and independent
source authentication are NOT verified. The new helper is **not connected** to
any real V10 process. The SQLite readback is structural integrity relative to
the stored chain, NOT an external signed witness or proof of original market
truth; replacing the entire DB and its initial anchor is not detectable without
independent retention. Do not label it a verified Windows durability solution,
do not deploy, and never publish private database bytes.
