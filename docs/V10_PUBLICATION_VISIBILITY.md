# V10 local publication visibility (P0-10)

The Gateway reads **only** the existing Watcher-owned
\`<RepoRoot>/ms2_live/kioxia_watcher_live.json\`, checks its size, published
schema/source identifier, explicit JST offset, file modification age, and
controller-verified Watcher process status. It exposes only
\`watcher_observed_at_offset\`, \`watcher_timestamp_timezone\`, and
\`watcher_publication_state\` through the existing loopback \`/health\`
response. It never exports trade records or CSV data. The existing Collector
publication check uses its already-published timestamp.

The UI independently polls the same-origin \`/health\`, distinguishing recent
JSON **publication** from stale, unknown, or unverified sources. A recent
publication DOES NOT establish that ticks were recently observed, that sources
are independently authenticated, or that signals are fit for trading.

Brain has no independently verified timestamp owner in this V10 tree and
remains \`UNKNOWN_NOT_PUBLISHED\`. Consequently all four-source evidence and
\`source_authenticated\` remain unverified and every real order route remains
disabled. The old September-25 static analysis stays labelled as historical.
This PR is a Draft, has not been merged or deployed to the OWNER PC.

Limitations: Watcher executable may be launched from a different folder than
\`RepoRoot/ms2_live\`; in that case the evidence remains UNAVAILABLE, rather
than trying untrusted directory discovery or treating a process status as data.
Windows CI invokes only a synthetic self-test and does not validate live Excel.
